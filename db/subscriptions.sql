\set ON_ERROR_STOP on
\getenv replication_password SIGTEC_REPLICATION_PASSWORD

-- Cada campus recibe las otras cuatro publicaciones (4 x 8 tablas) y estilos.
-- Los nombres de las cuatro suscripciones existentes permanecen intactos.
CREATE TEMP TABLE bootstrap_subscriptions AS
SELECT target_node, sub_name, publications, slot_name, expected_tables,
       'host=' || publisher_node || ' port=5432 dbname=sig_tec user=sigtec_repl password=' || :'replication_password' AS conninfo
FROM (VALUES
    ('central', 'sub_central_cartago', 'cartago', 'pub_cartago_edificios', 'slot_central_cartago', 8),
    ('central', 'sub_central_san_jose', 'san_jose', 'pub_san_jose_capas', 'slot_central_san_jose', 8),
    ('central', 'sub_central_san_carlos', 'san_carlos', 'pub_san_carlos_edificios', 'slot_central_san_carlos', 8),
    ('central', 'sub_central_alajuela', 'alajuela', 'pub_alajuela_capas', 'slot_central_alajuela', 8),
    ('central', 'sub_central_limon', 'limon', 'pub_limon_capas', 'slot_central_limon', 8),
    ('cartago', 'sub_cartago_central', 'central', 'pub_san_jose_capas,pub_san_carlos_edificios,pub_alajuela_capas,pub_limon_capas,pub_layer_styles', 'slot_cartago_central', 33),
    ('san_jose', 'sub_san_jose_central', 'central', 'pub_cartago_edificios,pub_san_carlos_edificios,pub_alajuela_capas,pub_limon_capas,pub_layer_styles', 'slot_san_jose_central', 33),
    ('san_carlos', 'sub_san_carlos_central', 'central', 'pub_cartago_edificios,pub_san_jose_capas,pub_alajuela_capas,pub_limon_capas,pub_layer_styles', 'slot_san_carlos_central', 33),
    ('alajuela', 'sub_alajuela_central', 'central', 'pub_cartago_edificios,pub_san_jose_capas,pub_san_carlos_edificios,pub_limon_capas,pub_layer_styles', 'slot_alajuela_central', 33),
    ('limon', 'sub_limon_central', 'central', 'pub_cartago_edificios,pub_san_jose_capas,pub_san_carlos_edificios,pub_alajuela_capas,pub_layer_styles', 'slot_limon_central', 33)
) AS desired(target_node, sub_name, publisher_node, publications, slot_name, expected_tables)
WHERE target_node = :'node';

SELECT format(
    'CREATE SUBSCRIPTION %I CONNECTION %L PUBLICATION %s WITH (slot_name = %L, create_slot = false, copy_data = true, origin = ''any'')',
    desired.sub_name, desired.conninfo, desired.publications, desired.slot_name
)
FROM bootstrap_subscriptions AS desired
WHERE NOT EXISTS (SELECT 1 FROM pg_subscription WHERE subname = desired.sub_name) \gexec

-- SET PUBLICATION conserva el slot; REFRESH añade las tablas nuevas sin
-- volver a copiar las que ya están sincronizadas.
SELECT format('ALTER SUBSCRIPTION %I SET PUBLICATION %s WITH (refresh = false)', desired.sub_name, desired.publications)
FROM bootstrap_subscriptions AS desired
JOIN pg_subscription AS existing_sub ON existing_sub.subname = desired.sub_name
WHERE existing_sub.subpublications IS DISTINCT FROM string_to_array(desired.publications, ',') \gexec

SELECT format('ALTER SUBSCRIPTION %I REFRESH PUBLICATION WITH (copy_data = true)', desired.sub_name)
FROM bootstrap_subscriptions AS desired
JOIN pg_subscription AS existing_sub ON existing_sub.subname = desired.sub_name
WHERE (
    SELECT count(*) FROM pg_subscription_rel WHERE srsubid = existing_sub.oid
) <> desired.expected_tables \gexec
