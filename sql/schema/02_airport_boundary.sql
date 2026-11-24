-- =============================================================================
-- 导入/刷新机场边界表 main.airport_boundary
-- 前置条件：会话已执行 LOAD spatial;（Quack DataGrip 初始化脚本已自动加载）
-- =============================================================================

SET VARIABLE boundary_geojson_path = 'D:/code/adsb-processing/data/Geojson/airport_boundary.geojson';
SET VARIABLE airport_iata = 'PEK';

CREATE OR REPLACE TABLE main.airport_boundary AS
SELECT *
FROM st_read(getvariable('boundary_geojson_path'))
WHERE iata = getvariable('airport_iata');

DESCRIBE main.airport_boundary;
SELECT COUNT(*) AS boundary_count FROM main.airport_boundary;
