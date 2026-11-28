-- Estado compacto para la demostración. No modifica datos ni configuración.
-- Ejecutar con psql -v ON_ERROR_STOP=1 -P pager=off sobre cada nodo.
BEGIN READ ONLY;

SELECT current_database() AS base,
       current_setting('server_version') AS postgresql,
       postgis_lib_version() AS postgis;

WITH objetos AS (
    SELECT 'edificios' AS capa, id, campus_id, geom::geometry AS geom,
           'ST_Polygon' AS tipo_esperado FROM sig.edificios
    UNION ALL SELECT 'carreteras', id, campus_id, geom, 'ST_LineString' FROM sig.carreteras
    UNION ALL SELECT 'aceras', id, campus_id, geom, 'ST_LineString' FROM sig.aceras
    UNION ALL SELECT 'parqueos', id, campus_id, geom, 'ST_Polygon' FROM sig.parqueos
    UNION ALL SELECT 'zonas_verdes', id, campus_id, geom, 'ST_Polygon' FROM sig.zonas_verdes
    UNION ALL SELECT 'puntos_interes', id, campus_id, geom, 'ST_Point' FROM sig.puntos_interes
    UNION ALL SELECT 'iluminacion', id, campus_id, geom, 'ST_Point' FROM sig.iluminacion
    UNION ALL SELECT 'accesibilidad', id, campus_id, geom, 'ST_LineString' FROM sig.accesibilidad
)
SELECT COALESCE(capa, 'TOTAL') AS capa,
       COUNT(*) AS objetos,
       COUNT(DISTINCT id) AS ids_unicos,
       COUNT(DISTINCT campus_id) AS campus,
       COUNT(*) FILTER (WHERE geom IS NOT NULL AND ST_IsValid(geom)
           AND NOT ST_IsEmpty(geom) AND ST_SRID(geom) = 8908
           AND ST_GeometryType(geom) = tipo_esperado) AS geometrias_correctas,
       COUNT(*) FILTER (WHERE campus_id BETWEEN 1 AND 5
           AND mod(id - campus_id, 5) = 0) AS ids_clase_campus
FROM objetos
GROUP BY GROUPING SETS ((capa), ())
ORDER BY GROUPING(capa), capa;

SELECT id, campus_id, nombre FROM sig.edificios ORDER BY campus_id, id;

SELECT s.subname AS suscripcion, s.subenabled AS habilitada,
       COUNT(r.srrelid) AS tablas,
       COUNT(r.srrelid) FILTER (WHERE r.srsubstate = 'r') AS tablas_listas
FROM pg_subscription AS s
LEFT JOIN pg_subscription_rel AS r ON r.srsubid = s.oid
GROUP BY s.subname, s.subenabled
ORDER BY s.subname;

SELECT slot_name AS slot, active AS activo
FROM pg_replication_slots ORDER BY slot_name;

SELECT COUNT(*) AS transacciones_preparadas FROM pg_prepared_xacts;

SELECT COUNT(*) AS estilos,
       COUNT(*) FILTER (WHERE useasdefault) AS predeterminados
FROM public.layer_styles;

COMMIT;
