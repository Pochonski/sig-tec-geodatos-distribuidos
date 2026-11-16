\set ON_ERROR_STOP on

\if :is_cartago
WITH marca AS (
    INSERT INTO sig.seed_aplicada (nombre)
    SELECT 'cartago.edificios' WHERE :'node' = 'cartago'
    ON CONFLICT DO NOTHING RETURNING 1
)
INSERT INTO cartago.edificios (id, campus_id, nombre, codigo, area, pisos, geom)
SELECT nextval('cartago.sigtec_ids'), 1, 'Biblioteca ficticia de Cartago', 'CT-PRUEBA',
       1200, 2,
       ST_Transform(
           ST_GeomFromText('POLYGON((-83.910 9.848, -83.9098 9.848, -83.9098 9.8482, -83.910 9.8482, -83.910 9.848))', 4326),
           8908
       )
WHERE EXISTS (SELECT 1 FROM marca);
\endif

\if :is_san_carlos
WITH marca AS (
    INSERT INTO sig.seed_aplicada (nombre)
    SELECT 'san_carlos.edificios' WHERE :'node' = 'san_carlos'
    ON CONFLICT DO NOTHING RETURNING 1
)
INSERT INTO san_carlos.edificios (id, campus_id, nombre, codigo, area, pisos, geom)
SELECT nextval('san_carlos.sigtec_ids'), 3, 'Laboratorio ficticio de San Carlos', 'SC-PRUEBA',
       850, 1,
       ST_Transform(
           ST_GeomFromText('POLYGON((-84.516 10.359, -84.5158 10.359, -84.5158 10.3592, -84.516 10.3592, -84.516 10.359))', 4326),
           8908
       )
WHERE EXISTS (SELECT 1 FROM marca);
\endif
