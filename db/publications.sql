\set ON_ERROR_STOP on

SELECT 'CREATE PUBLICATION pub_cartago_edificios FOR TABLE cartago.edificios'
WHERE :'node' IN ('cartago', 'central')
  AND NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'pub_cartago_edificios') \gexec

SELECT 'CREATE PUBLICATION pub_san_carlos_edificios FOR TABLE san_carlos.edificios'
WHERE :'node' IN ('san_carlos', 'central')
  AND NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'pub_san_carlos_edificios') \gexec

SELECT 'CREATE PUBLICATION pub_layer_styles FOR TABLE public.layer_styles'
WHERE :'node' = 'central'
  AND NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'pub_layer_styles') \gexec
