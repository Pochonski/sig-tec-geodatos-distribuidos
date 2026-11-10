\set ON_ERROR_STOP on
\getenv replication_password SIGTEC_REPLICATION_PASSWORD

SELECT format(
    'CREATE SUBSCRIPTION sub_central_cartago CONNECTION %L PUBLICATION pub_cartago_edificios WITH (slot_name = %L, create_slot = false, copy_data = true, origin = ''any'')',
    'host=cartago port=5432 dbname=sig_tec user=sigtec_repl password=' || :'replication_password',
    'slot_central_cartago'
)
WHERE :'node' = 'central'
  AND NOT EXISTS (SELECT 1 FROM pg_subscription WHERE subname = 'sub_central_cartago') \gexec

SELECT format(
    'CREATE SUBSCRIPTION sub_central_san_carlos CONNECTION %L PUBLICATION pub_san_carlos_edificios WITH (slot_name = %L, create_slot = false, copy_data = true, origin = ''any'')',
    'host=san_carlos port=5432 dbname=sig_tec user=sigtec_repl password=' || :'replication_password',
    'slot_central_san_carlos'
)
WHERE :'node' = 'central'
  AND NOT EXISTS (SELECT 1 FROM pg_subscription WHERE subname = 'sub_central_san_carlos') \gexec

SELECT format(
    'CREATE SUBSCRIPTION sub_cartago_central CONNECTION %L PUBLICATION pub_san_carlos_edificios, pub_layer_styles WITH (slot_name = %L, create_slot = false, copy_data = true, origin = ''any'')',
    'host=central port=5432 dbname=sig_tec user=sigtec_repl password=' || :'replication_password',
    'slot_cartago_central'
)
WHERE :'node' = 'cartago'
  AND NOT EXISTS (SELECT 1 FROM pg_subscription WHERE subname = 'sub_cartago_central') \gexec

SELECT format(
    'CREATE SUBSCRIPTION sub_san_carlos_central CONNECTION %L PUBLICATION pub_cartago_edificios, pub_layer_styles WITH (slot_name = %L, create_slot = false, copy_data = true, origin = ''any'')',
    'host=central port=5432 dbname=sig_tec user=sigtec_repl password=' || :'replication_password',
    'slot_san_carlos_central'
)
WHERE :'node' = 'san_carlos'
  AND NOT EXISTS (SELECT 1 FROM pg_subscription WHERE subname = 'sub_san_carlos_central') \gexec
