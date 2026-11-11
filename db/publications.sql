\set ON_ERROR_STOP on

-- El nombre de las publicaciones existentes se conserva para no recrear slots
-- ni suscripciones durante la ampliación de edificios a ocho capas.
CREATE TEMP TABLE bootstrap_publications AS
SELECT desired.pubname,
       string_agg(format('%I.%I', desired.schema_name, layer.name), ', ' ORDER BY layer.position) AS tables_sql,
       array_agg(desired.schema_name || '.' || layer.name ORDER BY layer.name) AS table_names
FROM (VALUES
    ('pub_cartago_edificios', 'cartago'),
    ('pub_san_jose_capas', 'san_jose'),
    ('pub_san_carlos_edificios', 'san_carlos'),
    ('pub_alajuela_capas', 'alajuela'),
    ('pub_limon_capas', 'limon')
) AS desired(pubname, schema_name)
CROSS JOIN LATERAL unnest(ARRAY[
    'edificios', 'carreteras', 'aceras', 'parqueos',
    'zonas_verdes', 'puntos_interes', 'iluminacion', 'accesibilidad'
]) WITH ORDINALITY AS layer(name, position)
WHERE :'node' = 'central' OR :'node' = desired.schema_name
GROUP BY desired.pubname, desired.schema_name;

SELECT format('CREATE PUBLICATION %I FOR TABLE %s', desired.pubname, desired.tables_sql)
FROM bootstrap_publications AS desired
WHERE NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = desired.pubname) \gexec

SELECT format('ALTER PUBLICATION %I SET TABLE %s', desired.pubname, desired.tables_sql)
FROM bootstrap_publications AS desired
WHERE (
    SELECT array_agg(schemaname || '.' || tablename ORDER BY schemaname, tablename)
    FROM pg_publication_tables
    WHERE pubname = desired.pubname
) IS DISTINCT FROM desired.table_names \gexec

SELECT 'CREATE PUBLICATION pub_layer_styles FOR TABLE public.layer_styles'
WHERE :'node' = 'central'
  AND NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'pub_layer_styles') \gexec

SELECT 'ALTER PUBLICATION pub_layer_styles SET TABLE public.layer_styles'
WHERE :'node' = 'central'
  AND (
      SELECT array_agg(schemaname || '.' || tablename)
      FROM pg_publication_tables
      WHERE pubname = 'pub_layer_styles'
  ) IS DISTINCT FROM ARRAY['public.layer_styles']::text[] \gexec
