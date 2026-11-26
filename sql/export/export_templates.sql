-- =============================================================================
-- 常用 CSV 导出模板（PostgreSQL psql \copy）
-- 使用方式：在 psql 中执行，或在 DataGrip 中运行内部 SELECT 后导出 CSV。
-- =============================================================================

-- 1. 导出全库去重机位清单（供 scripts/compare_stands.py 使用）
SELECT DISTINCT
    CASE WHEN stand_is_overridden THEN stand_override ELSE raw_stand_position END AS stand
FROM public.flights
WHERE (CASE WHEN stand_is_overridden THEN stand_override ELSE raw_stand_position END) IS NOT NULL
ORDER BY stand;