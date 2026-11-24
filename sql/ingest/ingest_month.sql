-- =============================================================================
-- 单月 ADS-B 数据增量导入脚本（供 DataGrip 执行）
-- 特性：
--   1. 所有清洗、空间过滤、速度单位换算（km/h -> kt）仅在临时 staging 表中执行，
--      绝不影响已有月份数据或人工修正过的机位。
--   2. 同一 source_month 可幂等重跑（先删当月再插，不触碰其他月份）。
--   3. 自动过滤与历史月份完全重复的跨月边界观测点（按 flight_id, timestamp, lon, lat）。
--   4. 按 (flight_id, timestamp) 有序写入，优化 DuckDB Zone Map 查询性能。
--
-- 使用方式：
--   仅修改下方 4 个 SET VARIABLE 参数后，按顺序执行即可。
--   （首次建库请先执行 sql/schema/01_core_tables.sql 与 02_airport_boundary.sql）
-- =============================================================================

-- 1. 参数配置（每次导入新月份只需改这里）
SET VARIABLE source_month       = '2024-07';
SET VARIABLE csv_path           = 'D:/code/adsb-processing/data/ADS-B/M_adsb_data_2024-07.csv';
SET VARIABLE airport_name       = '北京首都';
SET VARIABLE max_groundspeed_kt = 30.0;

-- 2. 读取单月 CSV 到会话级临时表（不落盘到主库文件）
CREATE OR REPLACE TEMP TABLE staging_adsb_raw AS
SELECT * RENAME (
    time_  AS timestamp,
    lon    AS longitude,
    lat    AS latitude,
    height AS altitude,
    speed  AS groundspeed,
    vspeed AS vertical_rate,
    fnum   AS number,
    angle  AS track
)
FROM read_csv(
    getvariable('csv_path'),
    header = TRUE,
    types = {
        'dep_stand_position': 'VARCHAR',
        'arr_stand_position': 'VARCHAR'
    }
);

SELECT COUNT(*) AS raw_row_count FROM staging_adsb_raw;

-- 3. 空间粗筛（仅保留落入机场边界内的观测）
DELETE FROM staging_adsb_raw AS a
WHERE NOT EXISTS (
    SELECT 1
    FROM main.airport_boundary AS airport
    WHERE ST_Covers(airport.geom, ST_Point(a.longitude, a.latitude))
);

SELECT COUNT(*) AS in_boundary_row_count FROM staging_adsb_raw;

-- 4. 速度单位换算（km/h -> kt）与场面速度过滤（仅作用于本批 staging 数据）
UPDATE staging_adsb_raw
SET groundspeed = groundspeed * 0.54
WHERE groundspeed IS NOT NULL;

DELETE FROM staging_adsb_raw
WHERE groundspeed > getvariable('max_groundspeed_kt');

SELECT COUNT(*) AS surface_row_count FROM staging_adsb_raw;

-- 5. 入库前异常检查：检查缺少 actual_arr / actual_dep 的航班（这类行无法拼接 flight_id，将被跳过）
SELECT
    CASE
        WHEN dst_name = getvariable('airport_name') THEN 'arrival'
        WHEN org_name = getvariable('airport_name') THEN 'departure'
    END AS movement,
    number,
    COUNT(*) AS missing_actual_time_rows
FROM staging_adsb_raw
WHERE (dst_name = getvariable('airport_name') AND actual_arr IS NULL)
   OR (org_name = getvariable('airport_name') AND actual_dep IS NULL)
GROUP BY 1, 2
ORDER BY 1, 3 DESC;

-- 6. 单事务幂等写入正式表（先清当月，再按序去重写入，并登记批次元数据）
BEGIN TRANSACTION;

DELETE FROM main.adsb_arr WHERE source_month = getvariable('source_month');
DELETE FROM main.adsb_dep WHERE source_month = getvariable('source_month');

INSERT INTO main.adsb_arr (
    number, org_name, dst_name, r_type, a_num,
    org_runway, dst_runway, dep_stand_position, arr_stand_position,
    sche_dep, sche_arr, actual_dep, actual_arr,
    timestamp, longitude, latitude, altitude, groundspeed, vertical_rate, track,
    org_tinezone, dst_tinezone, actual_deptime, actual_arrtime, p_time,
    flight_id, source_month
)
WITH candidates AS (
    SELECT
        number, org_name, dst_name, r_type, a_num,
        org_runway, dst_runway, dep_stand_position, arr_stand_position,
        sche_dep, sche_arr, actual_dep, actual_arr,
        timestamp, longitude, latitude, altitude, groundspeed, vertical_rate, track,
        org_tinezone, dst_tinezone, actual_deptime, actual_arrtime, p_time,
        number || '_' || STRFTIME(actual_arr, '%Y%m%d%H%M%S') AS flight_id,
        getvariable('source_month') AS source_month
    FROM staging_adsb_raw
    WHERE dst_name = getvariable('airport_name')
      AND number IS NOT NULL
      AND actual_arr IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY number || '_' || STRFTIME(actual_arr, '%Y%m%d%H%M%S'),
                     timestamp, longitude, latitude
        ORDER BY p_time
    ) = 1
)
SELECT c.*
FROM candidates AS c
WHERE NOT EXISTS (
    SELECT 1
    FROM main.adsb_arr AS existing
    WHERE existing.flight_id = c.flight_id
      AND existing.timestamp = c.timestamp
      AND existing.longitude = c.longitude
      AND existing.latitude = c.latitude
)
ORDER BY c.flight_id, c.timestamp;

INSERT INTO main.adsb_dep (
    number, org_name, dst_name, r_type, a_num,
    org_runway, dst_runway, dep_stand_position, arr_stand_position,
    sche_dep, sche_arr, actual_dep, actual_arr,
    timestamp, longitude, latitude, altitude, groundspeed, vertical_rate, track,
    org_tinezone, dst_tinezone, actual_deptime, actual_arrtime, p_time,
    flight_id, source_month
)
WITH candidates AS (
    SELECT
        number, org_name, dst_name, r_type, a_num,
        org_runway, dst_runway, dep_stand_position, arr_stand_position,
        sche_dep, sche_arr, actual_dep, actual_arr,
        timestamp, longitude, latitude, altitude, groundspeed, vertical_rate, track,
        org_tinezone, dst_tinezone, actual_deptime, actual_arrtime, p_time,
        number || '_' || STRFTIME(actual_dep, '%Y%m%d%H%M%S') AS flight_id,
        getvariable('source_month') AS source_month
    FROM staging_adsb_raw
    WHERE org_name = getvariable('airport_name')
      AND number IS NOT NULL
      AND actual_dep IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY number || '_' || STRFTIME(actual_dep, '%Y%m%d%H%M%S'),
                     timestamp, longitude, latitude
        ORDER BY p_time
    ) = 1
)
SELECT c.*
FROM candidates AS c
WHERE NOT EXISTS (
    SELECT 1
    FROM main.adsb_dep AS existing
    WHERE existing.flight_id = c.flight_id
      AND existing.timestamp = c.timestamp
      AND existing.longitude = c.longitude
      AND existing.latitude = c.latitude
)
ORDER BY c.flight_id, c.timestamp;

INSERT INTO main.ingest_batches (
    source_month, source_file, imported_at,
    arr_rows, arr_flights, dep_rows, dep_flights
)
SELECT
    getvariable('source_month'),
    getvariable('csv_path'),
    current_timestamp,
    (SELECT COUNT(*) FROM main.adsb_arr WHERE source_month = getvariable('source_month')),
    (SELECT COUNT(DISTINCT flight_id) FROM main.adsb_arr WHERE source_month = getvariable('source_month')),
    (SELECT COUNT(*) FROM main.adsb_dep WHERE source_month = getvariable('source_month')),
    (SELECT COUNT(DISTINCT flight_id) FROM main.adsb_dep WHERE source_month = getvariable('source_month'))
ON CONFLICT (source_month) DO UPDATE SET
    source_file = excluded.source_file,
    imported_at = excluded.imported_at,
    arr_rows    = excluded.arr_rows,
    arr_flights = excluded.arr_flights,
    dep_rows    = excluded.dep_rows,
    dep_flights = excluded.dep_flights;

COMMIT;

-- 7. 清理临时表并查看各月入库汇总
DROP TABLE IF EXISTS staging_adsb_raw;
SELECT * FROM main.ingest_batches ORDER BY source_month;
