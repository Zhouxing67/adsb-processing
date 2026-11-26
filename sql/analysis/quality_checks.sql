-- =============================================================================
-- ADS-B 数据质量检查与统计查询模板（PostgreSQL）
-- =============================================================================

-- 1. 按月统计进/离港航班数与观测点数
SELECT
    movement,
    source_month,
    COUNT(*) AS flight_count,
    SUM(point_count) AS row_count
FROM public.flights
GROUP BY movement, source_month
ORDER BY source_month, movement;

-- 2. 单航班观测点数分布（<15 / <30 / >=30）
SELECT
    movement,
    COUNT(*) AS total_flights,
    ROUND(COUNT(*) FILTER (WHERE point_count < 15) * 100.0 / NULLIF(COUNT(*), 0), 2) AS pct_lt_15,
    ROUND(COUNT(*) FILTER (WHERE point_count < 30) * 100.0 / NULLIF(COUNT(*), 0), 2) AS pct_lt_30,
    ROUND(COUNT(*) FILTER (WHERE point_count >= 30) * 100.0 / NULLIF(COUNT(*), 0), 2) AS pct_ge_30
FROM public.flights
GROUP BY movement
ORDER BY movement;

-- 3. 存在多值冲突（机位/跑道/航班号）的航班清单
SELECT
    movement,
    flight_id,
    number,
    stand_is_overridden,
    stand_override,
    conflict_fields
FROM public.flights
WHERE conflict_fields <> '{}'::jsonb
ORDER BY movement, flight_id;

-- 4. 分区分布健康检查（确认 adsb_observations_default 为 0 行）
SELECT
    c.relname AS partition_name,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
FROM pg_inherits i
JOIN pg_class c ON c.oid = i.inhrelid
JOIN pg_class p ON p.oid = i.inhparent
WHERE p.relname = 'adsb_observations'
ORDER BY c.relname;

-- 5. 验证航班集合（与 FlightCatalogueRepository.validation_flights 口径一致）
WITH cohort AS (
    SELECT
        flight_id,
        CASE WHEN movement = 'departure' THEN 'dep' ELSE 'arr' END AS movement,
        CASE WHEN stand_is_overridden THEN stand_override ELSE raw_stand_position END AS stand,
        point_count AS flight_points
    FROM public.flights
    WHERE point_count >= 30
      AND (
          (movement = 'departure' AND org_runway IS NOT NULL)
          OR (movement = 'arrival' AND dst_runway IS NOT NULL)
      )
)
SELECT
    flight_id,
    movement,
    stand,
    flight_points,
    COUNT(*) OVER () AS total_flights
FROM cohort
WHERE stand IS NOT NULL
  AND stand NOT IN ('952L', '14', '504', '506', '951L', '952R')
ORDER BY movement, flight_id, stand;
