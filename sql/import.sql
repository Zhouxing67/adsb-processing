--- 导入PEK机场的边界数据 ---
CREATE
OR REPLACE TABLE airport_boundary AS
SELECT *
FROM st_read('D:\code\adsb-processing\data\Geojson\airport_boundary.geojson');
DELETE
FROM airport_boundary
WHERE iata <> 'PEK'
   OR iata IS NULL;

DESCRIBE airport_boundary;

--- 导入ADS-B轨迹数据 ---
CREATE
OR REPLACE TABLE ADSB_202406 AS
SELECT * exclude(org_tinezone, dst_tinezone, actual_deptime, actual_arrtime,p_time)
rename(time_ AS "timestamp",
lon AS longitude,
lat AS latitude,
height AS altitude,
speed AS groundspeed,
vspeed AS vertical_rate,
fnum AS NUMBER,
angle AS track
), CAST(NULL AS VARCHAR) AS flight_id
FROM read_csv('D:/code/adsb-processing/data/ADS-B/M_adsb_data_2024-06-2.csv',
              header = TRUE,
              types = {
                  'dep_stand_position': 'VARCHAR',
              'arr_stand_position': 'VARCHAR'});
SELECT COUNT(*)
FROM main.adsb_202406;

