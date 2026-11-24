-- =============================================================================
-- 核心业务表 DDL（DuckDB）
-- 适用场景：首次建库，或在增量导入前确保表结构已就绪。
-- 约定：
--   1. 所有表名与列名统一使用小写蛇形命名，不包含月份后缀。
--   2. 无时区 TIMESTAMP 列均按北京时间（Asia/Shanghai）语义解释。
--   3. groundspeed 单位为节（kt），在 staging 清洗阶段完成 km/h -> kt 换算。
-- =============================================================================

CREATE TABLE IF NOT EXISTS main.adsb_arr (
    number             VARCHAR,
    org_name           VARCHAR,
    dst_name           VARCHAR,
    r_type             VARCHAR,
    a_num              VARCHAR,
    org_runway         VARCHAR,
    dst_runway         VARCHAR,
    dep_stand_position VARCHAR,
    arr_stand_position VARCHAR,
    sche_dep           TIMESTAMP,
    sche_arr           TIMESTAMP,
    actual_dep         TIMESTAMP,
    actual_arr         TIMESTAMP,
    timestamp          TIMESTAMP,
    longitude          DOUBLE,
    latitude           DOUBLE,
    altitude           DOUBLE,
    groundspeed        DOUBLE,
    vertical_rate      DOUBLE,
    track              DOUBLE,
    org_tinezone       BIGINT,
    dst_tinezone       BIGINT,
    actual_deptime     BIGINT,
    actual_arrtime     BIGINT,
    p_time             BIGINT,
    flight_id          VARCHAR,
    source_month       VARCHAR
);

CREATE TABLE IF NOT EXISTS main.adsb_dep (
    number             VARCHAR,
    org_name           VARCHAR,
    dst_name           VARCHAR,
    r_type             VARCHAR,
    a_num              VARCHAR,
    org_runway         VARCHAR,
    dst_runway         VARCHAR,
    dep_stand_position VARCHAR,
    arr_stand_position VARCHAR,
    sche_dep           TIMESTAMP,
    sche_arr           TIMESTAMP,
    actual_dep         TIMESTAMP,
    actual_arr         TIMESTAMP,
    timestamp          TIMESTAMP,
    longitude          DOUBLE,
    latitude           DOUBLE,
    altitude           DOUBLE,
    groundspeed        DOUBLE,
    vertical_rate      DOUBLE,
    track              DOUBLE,
    org_tinezone       BIGINT,
    dst_tinezone       BIGINT,
    actual_deptime     BIGINT,
    actual_arrtime     BIGINT,
    p_time             BIGINT,
    flight_id          VARCHAR,
    source_month       VARCHAR
);

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
