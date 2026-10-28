--- 按照机场边界过滤数据 ---
INSTALL
spatial;
LOAD
spatial;

---  对ADS-B数据按照PEK机场进行粗筛 ---
DELETE
FROM adsb_202406 AS a
WHERE NOT EXISTS (SELECT 1
                  FROM airport_boundary AS airport
                  WHERE st_covers(
                                airport.geom,
                                st_point(a.longitude, a.latitude)
                        ));
SELECT COUNT(*)
FROM adsb_202406;


--- km/h转节 ---
UPDATE adsb_202406
SET groundspeed = groundspeed * 0.54
WHERE 1 = 1;


--- 按照速度过滤非场面数据 ---
DELETE
FROM main.adsb_202406
WHERE groundspeed > 30.0;
SELECT COUNT(*)
FROM main.adsb_202406;


--- 验证飞机的到港时间/离港时间是否缺失
SELECT t1.number
FROM main.adsb_202406 AS t1
WHERE t1.dst_name = '北京首都' AND t1.actual_arr IS NULL
   OR t1.org_name = '北京首都' AND t1.actual_dep IS NULL
GROUP BY t1.number;

--- 分表为到港航班，离港航班,同时生成航班标识符 ---
CREATE
OR REPLACE TABLE ADSB_202406_arr AS
SELECT *
FROM main.adsb_202406
WHERE dst_name = '北京首都';

CREATE
OR REPLACE TABLE ADSB_202406_dep AS
SELECT *
FROM main.adsb_202406
WHERE org_name = '北京首都';

UPDATE adsb_202406_dep
SET flight_id = number || '_' || strftime(actual_dep, '%Y%m%d%H%M%S')
WHERE 1 = 1;

UPDATE adsb_202406_arr
SET flight_id = number || '_' || strftime(actual_arr, '%Y%m%d%H%M%S')
WHERE 1 = 1;

--- 统计单航班的数据点 ---
SELECT  COUNT(*) filter (WHERE sample_num < 15) / COUNT(*) AS less_15,
        COUNT(*) filter (WHERE sample_num < 30) / COUNT(*) AS less_30,
        COUNT(*) filter (WHERE sample_num > 15) / COUNT(*) AS more_20
FROM (SELECT flight_id, COUNT(*) AS sample_num
      FROM main.adsb_202406_arr
      GROUP BY flight_id);

SELECT  COUNT(*) filter (WHERE sample_num < 15) / COUNT(*) AS less_15,
        COUNT(*) filter (WHERE sample_num < 30) / COUNT(*) AS less_30,
        COUNT(*) filter (WHERE sample_num > 15) / COUNT(*) AS more_20
FROM (SELECT flight_id, COUNT(*) AS sample_num
      FROM main.adsb_202406_dep
      GROUP BY flight_id);

SELECT COUNT(*) * 0.8  FROM (SELECT DISTINCT flight_id FROM main.adsb_202406_arr)
SELECT COUNT(*) * 0.6 FROM (SELECT DISTINCT flight_id FROM main.adsb_202406_dep)