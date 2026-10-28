COPY (
    SELECT *
    FROM main.adsb_202406_arr
    WHERE flight_id = (
        SELECT flight_id
        FROM main.adsb_202406_arr
        GROUP BY flight_id
        ORDER BY COUNT(*) DESC
        LIMIT 1
    )
)
TO 'D:/code/adsb-processing/data/ADS-B/one_flight.csv'
(FORMAT CSV, HEADER TRUE);

COPY (
    SELECT *
    FROM main.adsb_202406_arr
    WHERE flight_id IN (
        SELECT flight_id
        FROM main.adsb_202406_arr
        GROUP BY flight_id
        ORDER BY COUNT(*) DESC
        Limit 1000
    )
    ORDER BY flight_id, "timestamp"
)
TO 'D:/code/adsb-processing/data/ADS-B/more_15_arr.csv'
(FORMAT CSV, HEADER TRUE);

COPY (
    SELECT *
    FROM main.adsb_202406_dep
    WHERE flight_id IN (
        SELECT flight_id
        FROM main.adsb_202406_dep
        GROUP BY flight_id
        ORDER BY COUNT(*) DESC
        Limit 1000
    )
    ORDER BY flight_id, "timestamp"
)
TO 'D:/code/adsb-processing/data/ADS-B/more_15_dep.csv'
(FORMAT CSV, HEADER TRUE);