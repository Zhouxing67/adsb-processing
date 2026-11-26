-- =============================================================================
-- 核心业务表 DDL（PostgreSQL）
-- 适用场景：首次建库，或在增量导入/测试初始化前确保表结构已就绪。
-- 约定：
--   1. 所有表名与列名统一使用小写蛇形命名，位于 public schema。
--   2. 所有时间列统一使用 TIMESTAMPTZ（绝对时刻，原始北京时间按 Asia/Shanghai 解析）。
--   3. groundspeed 单位为节（kt），在入库前清洗阶段完成 km/h -> kt 换算。
--   4. 航班静态元数据与人工修正机位（stand_override）独立存于 public.flights，
--      与原始轨迹点表 public.adsb_observations 解耦，重导原始数据不会覆盖人工编辑。
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.flights (
    flight_pk          BIGSERIAL PRIMARY KEY,
    movement           TEXT NOT NULL CHECK (movement IN ('arrival', 'departure')),
    flight_id          TEXT NOT NULL,
    number             TEXT,
    a_num              TEXT,
    r_type             TEXT,
    org_name           TEXT,
    dst_name           TEXT,
    org_runway         TEXT,
    dst_runway         TEXT,
    raw_stand_position TEXT,
    stand_override     TEXT,
    stand_is_overridden BOOLEAN NOT NULL DEFAULT FALSE,
    sche_dep           TIMESTAMPTZ,
    sche_arr           TIMESTAMPTZ,
    actual_dep         TIMESTAMPTZ,
    actual_arr         TIMESTAMPTZ,
    start_time         TIMESTAMPTZ,
    end_time           TIMESTAMPTZ,
    point_count        INTEGER NOT NULL DEFAULT 0,
    number_count       INTEGER NOT NULL DEFAULT 0,
    stand_count        INTEGER NOT NULL DEFAULT 0,
    conflict_fields    JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_month       TEXT,
    stand_updated_at   TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (movement, flight_id)
);

CREATE INDEX IF NOT EXISTS idx_flights_movement_number
ON public.flights (movement, number)
WHERE number IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_flights_a_num
ON public.flights (a_num)
WHERE a_num IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_flights_start_time
ON public.flights (start_time);

CREATE INDEX IF NOT EXISTS idx_flights_actual_dep
ON public.flights (actual_dep)
WHERE actual_dep IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_flights_actual_arr
ON public.flights (actual_arr)
WHERE actual_arr IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.adsb_observations (
    flight_pk     BIGINT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    longitude     DOUBLE PRECISION NOT NULL,
    latitude      DOUBLE PRECISION NOT NULL,
    altitude      REAL,
    groundspeed   REAL,
    vertical_rate REAL,
    track         REAL,
    source_month  TEXT
) PARTITION BY RANGE (ts);

CREATE TABLE IF NOT EXISTS public.adsb_observations_default
PARTITION OF public.adsb_observations DEFAULT;

CREATE INDEX IF NOT EXISTS idx_adsb_observations_flight_ts
ON public.adsb_observations (flight_pk, ts);

CREATE OR REPLACE FUNCTION public.ensure_observations_month_partition(target_ts TIMESTAMPTZ)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    month_start TIMESTAMPTZ;
    month_end   TIMESTAMPTZ;
    part_name   TEXT;
BEGIN
    month_start := date_trunc('month', target_ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    month_end := month_start + INTERVAL '1 month';
    part_name := format('adsb_observations_%s', to_char(month_start AT TIME ZONE 'UTC', 'YYYY_MM'));

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS public.%I PARTITION OF public.adsb_observations '
        'FOR VALUES FROM (%L) TO (%L)',
        part_name,
        month_start,
        month_end
    );
    RETURN part_name;
END;
$$;

CREATE TABLE IF NOT EXISTS public.ingest_batches (
    source_month TEXT PRIMARY KEY,
    source_file  TEXT NOT NULL,
    imported_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    arr_rows     BIGINT NOT NULL,
    arr_flights  BIGINT NOT NULL,
    dep_rows     BIGINT NOT NULL,
    dep_flights  BIGINT NOT NULL,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS public.match_issues (
    issue_id   TEXT PRIMARY KEY,
    movement   TEXT NOT NULL CHECK (movement IN ('arrival', 'departure')),
    flight_id  TEXT NOT NULL,
    reason     TEXT,
    graph_id   TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (movement, flight_id)
);

CREATE TABLE IF NOT EXISTS public.route_library (
    route_id              TEXT PRIMARY KEY,
    graph_id              TEXT NOT NULL,
    movement              TEXT NOT NULL CHECK (movement IN ('arrival', 'departure')),
    stand_ref             TEXT NOT NULL,
    runway_ref            TEXT,
    runway_interface_node TEXT NOT NULL,
    edges_json            TEXT NOT NULL,
    edge_count            INTEGER NOT NULL,
    total_length_m        DOUBLE PRECISION NOT NULL,
    flight_count          INTEGER NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'candidate',
    source                TEXT NOT NULL DEFAULT 'matched',
    note                  TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_route_library_od
ON public.route_library (graph_id, movement, stand_ref, runway_ref);

ALTER TABLE public.route_library
ADD COLUMN IF NOT EXISTS flight_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS public.route_flight_matches (
    route_id  TEXT NOT NULL REFERENCES public.route_library(route_id) ON DELETE CASCADE,
    movement  TEXT NOT NULL CHECK (movement IN ('arrival', 'departure')),
    flight_id TEXT NOT NULL,
    PRIMARY KEY (route_id, flight_id)
);

CREATE INDEX IF NOT EXISTS idx_route_flight_matches_route
ON public.route_flight_matches (route_id);
