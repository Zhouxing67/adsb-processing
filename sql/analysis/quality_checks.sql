-- =============================================================================
-- ADS-B 数据质量检查与统计查询模板（通用多月版）
-- =============================================================================

SET VARIABLE lower_threshold = 30;
-- 留空（NULL）表示统计全部月份；填入如 '2024-06' 可限定单月分析
SET VARIABLE target_month = CAST(NULL AS VARCHAR);

-- 1. 按月统计进/离港行数与航班数
SELECT
    'arr' AS movement,
    source_month,
    COUNT(*) AS row_count,
    COUNT(DISTINCT flight_id) AS flight_count
FROM main.adsb_arr
GROUP BY source_month
UNION ALL
SELECT
    'dep' AS movement,
    source_month,
    COUNT(*) AS row_count,
    COUNT(DISTINCT flight_id) AS flight_count
FROM main.adsb_dep
GROUP BY source_month
ORDER BY source_month, movement;

-- 2. 单航班观测点数分布（<15 / <30 / >=30）
WITH flight_counts AS (
    SELECT 'arr' AS movement, flight_id, COUNT(*) AS sample_num
    FROM main.adsb_arr
    WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
    GROUP BY flight_id
    UNION ALL
    SELECT 'dep' AS movement, flight_id, COUNT(*) AS sample_num
    FROM main.adsb_dep
    WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
    GROUP BY flight_id
)
SELECT
    movement,
    COUNT(*) AS total_flights,
    COUNT(*) FILTER (WHERE sample_num < 15) * 1.0 / COUNT(*) AS ratio_lt_15,
    COUNT(*) FILTER (WHERE sample_num < 30) * 1.0 / COUNT(*) AS ratio_lt_30,
    COUNT(*) FILTER (WHERE sample_num >= 30) * 1.0 / COUNT(*) AS ratio_ge_30
FROM flight_counts
GROUP BY movement
ORDER BY movement;

-- 3. 机位一致性检查：同一航班存在多个不同非空机位
SELECT
    flight_id,
    'dep' AS movement,
    COUNT(DISTINCT dep_stand_position) AS stand_count,
    LIST(DISTINCT dep_stand_position) FILTER (WHERE dep_stand_position IS NOT NULL) AS stands
FROM main.adsb_dep
WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
GROUP BY flight_id
HAVING stand_count > 1
UNION ALL
SELECT
    flight_id,
    'arr' AS movement,
    COUNT(DISTINCT arr_stand_position) AS stand_count,
    LIST(DISTINCT arr_stand_position) FILTER (WHERE arr_stand_position IS NOT NULL) AS stands
FROM main.adsb_arr
WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
GROUP BY flight_id
HAVING stand_count > 1;

-- 4. 机位完整性检查：同一航班同时存在 NULL 和非 NULL 机位
SELECT
    flight_id,
    'dep' AS movement,
    COUNT(*) AS total_points,
    COUNT(dep_stand_position) AS valid_stand_points
FROM main.adsb_dep
WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
GROUP BY flight_id
HAVING valid_stand_points > 0 AND valid_stand_points < total_points
UNION ALL
SELECT
    flight_id,
    'arr' AS movement,
    COUNT(*) AS total_points,
    COUNT(arr_stand_position) AS valid_stand_points
FROM main.adsb_arr
WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
GROUP BY flight_id
HAVING valid_stand_points > 0 AND valid_stand_points < total_points;

-- 5. 跑道一致性检查：同一航班存在多个不同非空跑道
SELECT
    flight_id,
    'dep' AS movement,
    COUNT(DISTINCT org_runway) AS runway_count,
    LIST(DISTINCT org_runway) FILTER (WHERE org_runway IS NOT NULL) AS runways
FROM main.adsb_dep
WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
GROUP BY flight_id
HAVING runway_count > 1
UNION ALL
SELECT
    flight_id,
    'arr' AS movement,
    COUNT(DISTINCT dst_runway) AS runway_count,
    LIST(DISTINCT dst_runway) FILTER (WHERE dst_runway IS NOT NULL) AS runways
FROM main.adsb_arr
WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
GROUP BY flight_id
HAVING runway_count > 1;

-- 6. 跑道完整性检查：同一航班同时存在 NULL 和非 NULL 跑道
SELECT
    flight_id,
    'dep' AS movement,
    COUNT(*) AS total_points,
    COUNT(org_runway) AS valid_runway_points
FROM main.adsb_dep
WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
GROUP BY flight_id
HAVING valid_runway_points > 0 AND valid_runway_points < total_points
UNION ALL
SELECT
    flight_id,
    'arr' AS movement,
    COUNT(*) AS total_points,
    COUNT(dst_runway) AS valid_runway_points
FROM main.adsb_arr
WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
GROUP BY flight_id
HAVING valid_runway_points > 0 AND valid_runway_points < total_points;

-- 7. 验证航班集合（与 FlightCatalogueRepository.validation_flights 口径一致）
WITH flights_with_stand_and_runway AS (
    SELECT
        flight_id,
        'dep' AS movement,
        dep_stand_position AS stand,
        COUNT(*) AS flight_points
    FROM main.adsb_dep
    WHERE dep_stand_position IS NOT NULL
      AND dep_stand_position NOT IN ('952L', '14', '504', '506', '951L', '952R')
      AND org_runway IS NOT NULL
      AND (getvariable('target_month') IS NULL OR source_month = getvariable('target_month'))
    GROUP BY flight_id, dep_stand_position
    HAVING COUNT(*) >= getvariable('lower_threshold')

    UNION ALL

    SELECT
        flight_id,
        'arr' AS movement,
        arr_stand_position AS stand,
        COUNT(*) AS flight_points
    FROM main.adsb_arr
    WHERE arr_stand_position IS NOT NULL
      AND arr_stand_position NOT IN ('952L', '14', '504', '506', '951L', '952R')
      AND dst_runway IS NOT NULL
      AND (getvariable('target_month') IS NULL OR source_month = getvariable('target_month'))
    GROUP BY flight_id, arr_stand_position
    HAVING COUNT(*) >= getvariable('lower_threshold')
)
SELECT *, COUNT(*) OVER () AS total_flights
FROM flights_with_stand_and_runway
ORDER BY movement, flight_id, stand;
