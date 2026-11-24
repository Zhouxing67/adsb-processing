-- =============================================================================
-- 常用 CSV 导出模板（通用多月版）
-- 使用方式：在 DataGrip 中按需修改变量或选中单段 COPY 语句执行。
-- =============================================================================

SET VARIABLE export_min_points = 15;
-- 留空（NULL）表示导出全部月份；填入如 '2024-06' 可限定单月导出
SET VARIABLE target_month = CAST(NULL AS VARCHAR);

-- 1. 导出观测点数 >= export_min_points 的进港航班
COPY (
    SELECT a.*
    FROM main.adsb_arr AS a
    WHERE a.flight_id IN (
        SELECT flight_id
        FROM main.adsb_arr
        WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
        GROUP BY flight_id
        HAVING COUNT(*) >= getvariable('export_min_points')
    )
    ORDER BY a.flight_id, a.timestamp
)
TO 'D:/code/adsb-processing/data/ADS-B/more_15_arr.csv'
(FORMAT CSV, HEADER TRUE);

-- 2. 导出观测点数 >= export_min_points 的离港航班
COPY (
    SELECT d.*
    FROM main.adsb_dep AS d
    WHERE d.flight_id IN (
        SELECT flight_id
        FROM main.adsb_dep
        WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
        GROUP BY flight_id
        HAVING COUNT(*) >= getvariable('export_min_points')
    )
    ORDER BY d.flight_id, d.timestamp
)
TO 'D:/code/adsb-processing/data/ADS-B/more_15_dep.csv'
(FORMAT CSV, HEADER TRUE);

-- 3. 导出全库去重机位清单（供 scripts/compare_stands.py 使用）
COPY (
    SELECT dep_stand_position AS stand
    FROM main.adsb_dep
    WHERE dep_stand_position IS NOT NULL
    UNION
    SELECT arr_stand_position AS stand
    FROM main.adsb_arr
    WHERE arr_stand_position IS NOT NULL
    ORDER BY stand
)
TO 'D:/code/adsb-processing/data/ADS-B/stand.csv'
(FORMAT CSV, HEADER TRUE);
