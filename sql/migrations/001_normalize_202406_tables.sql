-- =============================================================================
-- 一次性迁移脚本 001：将 2024-06 单月表原地重命名为通用多月表
-- 特点：
--   1. 使用 ALTER TABLE RENAME 原地重命名，完整保留工作台人工编辑过的机位数据。
--   2. 为两张表补充 source_month 列并回填 '2024-06'。
--   3. 创建 main.ingest_batches 并登记 2024-06 基线批次记录。
-- 执行前提：
--   - 数据库中当前存在 main.adsb_202406_arr 和 main.adsb_202406_dep。
--   - 尚未存在 main.adsb_arr 和 main.adsb_dep。
-- =============================================================================

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS main.ingest_batches (
    source_month VARCHAR PRIMARY KEY,
    source_file  VARCHAR NOT NULL,
    imported_at  TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    arr_rows     BIGINT NOT NULL,
    arr_flights  BIGINT NOT NULL,
    dep_rows     BIGINT NOT NULL,
    dep_flights  BIGINT NOT NULL,
    note         VARCHAR
);

ALTER TABLE main.adsb_202406_arr RENAME TO adsb_arr;
ALTER TABLE main.adsb_202406_dep RENAME TO adsb_dep;

ALTER TABLE main.adsb_arr ADD COLUMN IF NOT EXISTS source_month VARCHAR;
UPDATE main.adsb_arr SET source_month = '2024-06' WHERE source_month IS NULL;

ALTER TABLE main.adsb_dep ADD COLUMN IF NOT EXISTS source_month VARCHAR;
UPDATE main.adsb_dep SET source_month = '2024-06' WHERE source_month IS NULL;

INSERT INTO main.ingest_batches (
    source_month, source_file, imported_at,
    arr_rows, arr_flights, dep_rows, dep_flights, note
)
SELECT
    '2024-06',
    'M_adsb_data_2024-06-2.csv',
    current_timestamp,
    (SELECT COUNT(*) FROM main.adsb_arr WHERE source_month = '2024-06'),
    (SELECT COUNT(DISTINCT flight_id) FROM main.adsb_arr WHERE source_month = '2024-06'),
    (SELECT COUNT(*) FROM main.adsb_dep WHERE source_month = '2024-06'),
    (SELECT COUNT(DISTINCT flight_id) FROM main.adsb_dep WHERE source_month = '2024-06'),
    'Migrated in-place from adsb_202406_arr / adsb_202406_dep'
ON CONFLICT (source_month) DO UPDATE SET
    arr_rows    = excluded.arr_rows,
    arr_flights = excluded.arr_flights,
    dep_rows    = excluded.dep_rows,
    dep_flights = excluded.dep_flights,
    imported_at = excluded.imported_at,
    note        = excluded.note;

COMMIT;

-- 迁移后校验
SHOW TABLES;
SELECT * FROM main.ingest_batches ORDER BY source_month;

-- 确认 adsb_arr / adsb_dep 数据无误后，可手动取消注释并删除旧的未切分中间表以释放空间：
-- DROP TABLE IF EXISTS main.adsb_202406;
-- CHECKPOINT;
