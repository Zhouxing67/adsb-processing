-- =============================================================================
-- 人工执行：ADS-B 异常/垃圾轨迹前置过滤脚本（DuckDB）
--
-- 设计定位：
--   - 仅由人工在数据库中按需执行，不进入 path_map 匹配主流程；
--   - 只依赖轨迹本身的物理与元数据特征（点数、总里程、空间跨度、单步跳变、OD 冲突），
--     不依赖机场路网；
--   - 支持：
--       1) 只读统计各异常类型占比；
--       2) 抽样预览被判为异常的航班，便于人工核对阈值；
--       3) 人工确认后，刷新 flight_quality_metrics / flight_whitelist，
--          或直接清理 adsb_arr / adsb_dep 中的异常航班（默认注释保护）。
-- =============================================================================

-- 可按机场尺度与数据质量调整阈值
SET VARIABLE target_month      = CAST(NULL AS VARCHAR); -- NULL=全量；如 '2024-06' 仅筛单月
SET VARIABLE min_point_count   = 10;     -- 最小有效观测点数
SET VARIABLE min_total_track_m = 150.0;  -- 最小累计轨迹长度（米），过滤原地静止/极短残片
SET VARIABLE min_bbox_span_m   = 100.0;  -- 最小空间包围盒对角跨度（米），过滤原地抖动
SET VARIABLE max_step_jump_m   = 400.0;  -- 允许的最大相邻观测点直线跳变距离（米），过滤断层/瞬移
SET VARIABLE max_time_gap_s    = 300.0;  -- 允许的最大相邻观测时间间隔（秒），过滤长信号黑洞

-- -----------------------------------------------------------------------------
-- 第 1 步（只读）：按异常类型汇总各维度拦截量，评估阈值是否合理
-- -----------------------------------------------------------------------------
WITH raw_points AS (
    SELECT
        'arrival' AS movement,
        flight_id,
        arr_stand_position AS stand_ref,
        dst_runway AS runway_ref,
        timestamp,
        longitude,
        latitude
    FROM main.adsb_arr
    WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')

    UNION ALL

    SELECT
        'departure' AS movement,
        flight_id,
        dep_stand_position AS stand_ref,
        org_runway AS runway_ref,
        timestamp,
        longitude,
        latitude
    FROM main.adsb_dep
    WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
),
ordered_points AS (
    SELECT
        movement,
        flight_id,
        NULLIF(TRIM(stand_ref), '') AS stand_ref,
        NULLIF(TRIM(runway_ref), '') AS runway_ref,
        timestamp,
        longitude,
        latitude,
        LAG(longitude) OVER (PARTITION BY movement, flight_id ORDER BY timestamp) AS prev_lon,
        LAG(latitude)  OVER (PARTITION BY movement, flight_id ORDER BY timestamp) AS prev_lat,
        LAG(timestamp) OVER (PARTITION BY movement, flight_id ORDER BY timestamp) AS prev_ts
    FROM raw_points
    WHERE longitude IS NOT NULL
      AND latitude IS NOT NULL
      AND timestamp IS NOT NULL
),
step_metrics AS (
    SELECT
        movement,
        flight_id,
        stand_ref,
        runway_ref,
        longitude,
        latitude,
        CASE
            WHEN prev_lon IS NULL THEN 0.0
            ELSE SQRT(
                POW((latitude - prev_lat) * 111320.0, 2) +
                POW((longitude - prev_lon) * 111320.0 * COS(RADIANS((latitude + prev_lat) / 2.0)), 2)
            )
        END AS step_m,
        CASE
            WHEN prev_ts IS NULL THEN 0.0
            ELSE EXTRACT(EPOCH FROM (timestamp - prev_ts))
        END AS step_s
    FROM ordered_points
),
flight_metrics AS (
    SELECT
        movement,
        flight_id,
        MIN(stand_ref) AS stand_ref,
        MIN(runway_ref) AS runway_ref,
        COUNT(DISTINCT stand_ref) AS stand_distinct,
        COUNT(DISTINCT runway_ref) AS runway_distinct,
        COUNT(*) AS point_count,
        COALESCE(MAX(step_m), 0.0) AS max_step_m,
        CASE WHEN COUNT(*) > 1 THEN SUM(step_m) / (COUNT(*) - 1) ELSE 0.0 END AS avg_step_m,
        COALESCE(SUM(step_m), 0.0) AS total_track_m,
        COALESCE(MAX(step_s), 0.0) AS max_time_gap_s,
        SQRT(
            POW((MAX(latitude) - MIN(latitude)) * 111320.0, 2) +
            POW((MAX(longitude) - MIN(longitude)) * 111320.0 * COS(RADIANS((MAX(latitude) + MIN(latitude)) / 2.0)), 2)
        ) AS bbox_span_m
    FROM step_metrics
    GROUP BY movement, flight_id
),
classified AS (
    SELECT
        *,
        CASE
            WHEN stand_distinct > 1 OR runway_distinct > 1 THEN 'conflicting_od'
            WHEN point_count < getvariable('min_point_count') THEN 'too_few_points'
            WHEN total_track_m < getvariable('min_total_track_m')
              OR bbox_span_m < getvariable('min_bbox_span_m') THEN 'stationary_or_short'
            WHEN max_step_m > getvariable('max_step_jump_m') THEN 'large_spatial_gap'
            WHEN max_time_gap_s > getvariable('max_time_gap_s') THEN 'large_time_gap'
            ELSE 'clean'
        END AS quality_status
    FROM flight_metrics
)
SELECT
    movement,
    quality_status,
    COUNT(*) AS flight_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY movement), 2) AS pct
FROM classified
GROUP BY movement, quality_status
ORDER BY movement, flight_count DESC;

-- -----------------------------------------------------------------------------
-- 第 2 步（只读）：抽样查看被判为异常的航班明细（按最大跳变/最短轨迹排序）
-- -----------------------------------------------------------------------------
-- 将第 1 步末尾的 SELECT 替换为以下查询即可查看具体 flight_id：
--
-- SELECT
--     movement,
--     flight_id,
--     quality_status,
--     stand_ref,
--     runway_ref,
--     point_count,
--     ROUND(total_track_m, 1) AS total_track_m,
--     ROUND(bbox_span_m, 1)   AS bbox_span_m,
--     ROUND(max_step_m, 1)    AS max_step_m,
--     ROUND(max_time_gap_s, 1) AS max_time_gap_s
-- FROM classified
-- WHERE quality_status <> 'clean'
-- ORDER BY quality_status, max_step_m DESC, point_count ASC
-- LIMIT 100;

-- -----------------------------------------------------------------------------
-- 第 3 步（人工确认后取消注释执行）：
--   方案 A：刷新 flight_quality_metrics 并写入干净航班到 flight_whitelist
-- -----------------------------------------------------------------------------
-- BEGIN TRANSACTION;
--
-- DELETE FROM main.flight_quality_metrics;
-- DELETE FROM main.flight_whitelist;
--
-- WITH raw_points AS (
--     SELECT
--         'arrival' AS movement,
--         flight_id,
--         arr_stand_position AS stand_ref,
--         dst_runway AS runway_ref,
--         timestamp,
--         longitude,
--         latitude
--     FROM main.adsb_arr
--     WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
--     UNION ALL
--     SELECT
--         'departure' AS movement,
--         flight_id,
--         dep_stand_position AS stand_ref,
--         org_runway AS runway_ref,
--         timestamp,
--         longitude,
--         latitude
--     FROM main.adsb_dep
--     WHERE getvariable('target_month') IS NULL OR source_month = getvariable('target_month')
-- ),
-- ordered_points AS (
--     SELECT
--         movement,
--         flight_id,
--         NULLIF(TRIM(stand_ref), '') AS stand_ref,
--         NULLIF(TRIM(runway_ref), '') AS runway_ref,
--         timestamp,
--         longitude,
--         latitude,
--         LAG(longitude) OVER (PARTITION BY movement, flight_id ORDER BY timestamp) AS prev_lon,
--         LAG(latitude)  OVER (PARTITION BY movement, flight_id ORDER BY timestamp) AS prev_lat,
--         LAG(timestamp) OVER (PARTITION BY movement, flight_id ORDER BY timestamp) AS prev_ts
--     FROM raw_points
--     WHERE longitude IS NOT NULL AND latitude IS NOT NULL AND timestamp IS NOT NULL
-- ),
-- step_metrics AS (
--     SELECT
--         movement,
--         flight_id,
--         stand_ref,
--         runway_ref,
--         longitude,
--         latitude,
--         CASE
--             WHEN prev_lon IS NULL THEN 0.0
--             ELSE SQRT(
--                 POW((latitude - prev_lat) * 111320.0, 2) +
--                 POW((longitude - prev_lon) * 111320.0 * COS(RADIANS((latitude + prev_lat) / 2.0)), 2)
--             )
--         END AS step_m,
--         CASE
--             WHEN prev_ts IS NULL THEN 0.0
--             ELSE EXTRACT(EPOCH FROM (timestamp - prev_ts))
--         END AS step_s
--     FROM ordered_points
-- )
-- INSERT INTO main.flight_quality_metrics (
--     movement, flight_id, stand_ref, runway_ref, stand_distinct,
--     point_count, max_step_m, avg_step_m, total_track_m, stand_dist_m, runway_dist_m
-- )
-- SELECT
--     movement,
--     flight_id,
--     CASE WHEN COUNT(DISTINCT stand_ref) = 1 THEN MIN(stand_ref) ELSE NULL END AS stand_ref,
--     CASE WHEN COUNT(DISTINCT runway_ref) = 1 THEN MIN(runway_ref) ELSE NULL END AS runway_ref,
--     COUNT(DISTINCT stand_ref) AS stand_distinct,
--     COUNT(*) AS point_count,
--     COALESCE(MAX(step_m), 0.0) AS max_step_m,
--     CASE WHEN COUNT(*) > 1 THEN SUM(step_m) / (COUNT(*) - 1) ELSE 0.0 END AS avg_step_m,
--     COALESCE(SUM(step_m), 0.0) AS total_track_m,
--     NULL AS stand_dist_m,
--     NULL AS runway_dist_m
-- FROM step_metrics
-- GROUP BY movement, flight_id;
--
-- INSERT INTO main.flight_whitelist (movement, flight_id, stand_ref, runway_ref)
-- SELECT movement, flight_id, stand_ref, runway_ref
-- FROM main.flight_quality_metrics
-- WHERE stand_distinct <= 1
--   AND point_count >= getvariable('min_point_count')
--   AND total_track_m >= getvariable('min_total_track_m')
--   AND max_step_m <= getvariable('max_step_jump_m');
--
-- COMMIT;

-- -----------------------------------------------------------------------------
-- 第 3 步（备选方案 B，破坏性操作，人工确认后取消注释执行）：
--   直接从 adsb_arr / adsb_dep 删除不在白名单中的异常航班
-- -----------------------------------------------------------------------------
-- BEGIN TRANSACTION;
--
-- DELETE FROM main.adsb_arr
-- WHERE (getvariable('target_month') IS NULL OR source_month = getvariable('target_month'))
--   AND flight_id NOT IN (
--       SELECT flight_id FROM main.flight_whitelist WHERE movement = 'arrival'
--   );
--
-- DELETE FROM main.adsb_dep
-- WHERE (getvariable('target_month') IS NULL OR source_month = getvariable('target_month'))
--   AND flight_id NOT IN (
--       SELECT flight_id FROM main.flight_whitelist WHERE movement = 'departure'
--   );
--
-- COMMIT;
