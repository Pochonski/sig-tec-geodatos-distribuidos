\set ON_ERROR_STOP on
\getenv cartago_password SIGTEC_CARTAGO_PASSWORD
\getenv san_jose_password SIGTEC_SAN_JOSE_PASSWORD
\getenv san_carlos_password SIGTEC_SAN_CARLOS_PASSWORD
\getenv alajuela_password SIGTEC_ALAJUELA_PASSWORD
\getenv limon_password SIGTEC_LIMON_PASSWORD
\getenv replication_password SIGTEC_REPLICATION_PASSWORD

CREATE EXTENSION IF NOT EXISTS postgis;

-- Las cuentas de demostración existen en el central y en su campus de origen.
SELECT format('CREATE ROLE %I LOGIN', 'demo_' || nombre)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE :campus_id IN (0, id)
  AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'demo_' || nombre) \gexec
SELECT 'CREATE ROLE sigtec_repl LOGIN REPLICATION'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sigtec_repl') \gexec
SELECT 'CREATE ROLE sigtec_editor_owner NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sigtec_editor_owner') \gexec
SELECT 'CREATE ROLE sigtec_auth_owner NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sigtec_auth_owner') \gexec

SELECT format('ALTER ROLE demo_cartago PASSWORD %L', :'cartago_password')
WHERE :campus_id IN (0, 1) \gexec
SELECT format('ALTER ROLE demo_san_jose PASSWORD %L', :'san_jose_password')
WHERE :campus_id IN (0, 2) \gexec
SELECT format('ALTER ROLE demo_san_carlos PASSWORD %L', :'san_carlos_password')
WHERE :campus_id IN (0, 3) \gexec
SELECT format('ALTER ROLE demo_alajuela PASSWORD %L', :'alajuela_password')
WHERE :campus_id IN (0, 4) \gexec
SELECT format('ALTER ROLE demo_limon PASSWORD %L', :'limon_password')
WHERE :campus_id IN (0, 5) \gexec
SELECT format('ALTER ROLE sigtec_repl PASSWORD %L', :'replication_password') \gexec

REVOKE CONNECT ON DATABASE sig_tec FROM PUBLIC;
GRANT CONNECT ON DATABASE sig_tec TO sigtec_repl;
SELECT format('GRANT CONNECT ON DATABASE sig_tec TO %I', 'demo_' || nombre)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE :campus_id IN (0, id) \gexec

CREATE SCHEMA IF NOT EXISTS cartago;
CREATE SCHEMA IF NOT EXISTS san_jose;
CREATE SCHEMA IF NOT EXISTS san_carlos;
CREATE SCHEMA IF NOT EXISTS alajuela;
CREATE SCHEMA IF NOT EXISTS limon;
CREATE SCHEMA IF NOT EXISTS sig;
CREATE SCHEMA IF NOT EXISTS auth;
REVOKE ALL ON SCHEMA cartago, san_jose, san_carlos, alajuela, limon, sig, auth FROM PUBLIC;

-- Los cinco esquemas físicos deben coincidir en los seis nodos. Solo el campus
-- propietario recibe una secuencia y permiso para escribir sus ocho tablas.
DO $$
DECLARE
    campus record;
    capa record;
BEGIN
    FOR campus IN
        SELECT * FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
                              ('alajuela', 4), ('limon', 5)) AS c(nombre, id)
    LOOP
        FOR capa IN
            SELECT * FROM (VALUES
                ('edificios', 'Polygon',
                 'nombre text NOT NULL, codigo text, area double precision, pisos integer'),
                ('carreteras', 'LineString',
                 'nombre text NOT NULL, tipo text, superficie text'),
                ('aceras', 'LineString',
                 'material text, ancho double precision, condicion text'),
                ('parqueos', 'Polygon',
                 'capacidad integer, tipo text, disponibilidad boolean'),
                ('zonas_verdes', 'Polygon',
                 'area double precision, tipo_vegetacion text'),
                ('puntos_interes', 'Point',
                 'nombre text NOT NULL, tipo text'),
                ('iluminacion', 'Point',
                 'codigo text, potencia double precision, estado text'),
                ('accesibilidad', 'LineString',
                 'tipo text')
            ) AS c(nombre, tipo, columnas)
        LOOP
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I.%I (
                    id bigint PRIMARY KEY,
                    campus_id smallint NOT NULL DEFAULT %s CHECK (campus_id = %s),
                    %s,
                    geom geometry(%s, 8908) NOT NULL
                )',
                campus.nombre, capa.nombre, campus.id, campus.id,
                capa.columnas, capa.tipo
            );
            EXECUTE format('REVOKE ALL ON %I.%I FROM PUBLIC', campus.nombre, capa.nombre);
            EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I.%I USING gist (geom)',
                           campus.nombre || '_' || capa.nombre || '_geom_idx',
                           campus.nombre, capa.nombre);
        END LOOP;
    END LOOP;
END;
$$;

SELECT format('CREATE SEQUENCE IF NOT EXISTS %I.sigtec_ids AS bigint START WITH %s INCREMENT BY 5',
              nombre, id)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE id = :campus_id \gexec

CREATE TABLE IF NOT EXISTS sig.seed_aplicada (nombre text PRIMARY KEY);
REVOKE ALL ON sig.seed_aplicada FROM PUBLIC;

-- Esta estructura coincide con layer_styles de QGIS 3.44.
CREATE TABLE IF NOT EXISTS public.layer_styles (
    id serial PRIMARY KEY,
    f_table_catalog varchar,
    f_table_schema varchar,
    f_table_name varchar,
    f_geometry_column varchar,
    styleName text,
    styleQML xml,
    styleSLD xml,
    useAsDefault boolean,
    description text,
    owner varchar(63) DEFAULT CURRENT_USER,
    ui xml,
    update_time timestamp DEFAULT CURRENT_TIMESTAMP,
    type varchar,
    r_raster_column varchar
);
REVOKE ALL ON public.layer_styles FROM PUBLIC;
GRANT USAGE ON SCHEMA cartago, san_jose, san_carlos, alajuela, limon TO sigtec_repl;
GRANT SELECT ON ALL TABLES IN SCHEMA cartago, san_jose, san_carlos, alajuela, limon TO sigtec_repl;
GRANT SELECT ON public.layer_styles TO sigtec_repl;

CREATE TABLE IF NOT EXISTS auth.cuentas (
    usuario name PRIMARY KEY,
    campus_id smallint NOT NULL
);
-- Amplía la restricción de la primera entrega sin tocar las cuentas existentes.
ALTER TABLE auth.cuentas DROP CONSTRAINT IF EXISTS cuentas_campus_id_check;
ALTER TABLE auth.cuentas ADD CONSTRAINT cuentas_campus_id_check
    CHECK (campus_id BETWEEN 1 AND 5);
REVOKE ALL ON auth.cuentas FROM PUBLIC;
REVOKE CREATE ON SCHEMA auth FROM sigtec_auth_owner;
GRANT USAGE ON SCHEMA auth TO sigtec_auth_owner;
GRANT SELECT ON auth.cuentas TO sigtec_auth_owner;

CREATE OR REPLACE FUNCTION auth.mi_campus()
RETURNS smallint
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT campus_id FROM auth.cuentas WHERE usuario = session_user;
$$;
ALTER FUNCTION auth.mi_campus() OWNER TO sigtec_auth_owner;
REVOKE ALL ON FUNCTION auth.mi_campus() FROM PUBLIC;
SELECT format('GRANT USAGE ON SCHEMA auth TO %I', 'demo_' || nombre)
FROM (VALUES ('cartago'), ('san_jose'), ('san_carlos'),
             ('alajuela'), ('limon')) AS campus(nombre)
WHERE :campus_id = 0 \gexec
SELECT format('GRANT EXECUTE ON FUNCTION auth.mi_campus() TO %I', 'demo_' || nombre)
FROM (VALUES ('cartago'), ('san_jose'), ('san_carlos'),
             ('alajuela'), ('limon')) AS campus(nombre)
WHERE :campus_id = 0 \gexec
INSERT INTO auth.cuentas (usuario, campus_id)
SELECT 'demo_' || nombre, id
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE :campus_id = 0
ON CONFLICT (usuario) DO UPDATE SET campus_id = EXCLUDED.campus_id;

-- El orden de las columnas de cada vista replica el de sus tablas físicas.
DO $$
DECLARE
    capa record;
    union_sql text;
BEGIN
    FOR capa IN
        SELECT * FROM (VALUES
            ('edificios', 'Polygon', 'nombre, codigo, area, pisos'),
            ('carreteras', 'LineString', 'nombre, tipo, superficie'),
            ('aceras', 'LineString', 'material, ancho, condicion'),
            ('parqueos', 'Polygon', 'capacidad, tipo, disponibilidad'),
            ('zonas_verdes', 'Polygon', 'area, tipo_vegetacion'),
            ('puntos_interes', 'Point', 'nombre, tipo'),
            ('iluminacion', 'Point', 'codigo, potencia, estado'),
            ('accesibilidad', 'LineString', 'tipo')
        ) AS c(nombre, tipo, atributos)
    LOOP
        SELECT string_agg(
            format('SELECT id, campus_id, %s, geom::geometry(%s, 8908) AS geom FROM %I.%I',
                   capa.atributos, capa.tipo, campus.nombre, capa.nombre),
            E'\nUNION ALL\n' ORDER BY campus.id
        ) INTO union_sql
        FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
                     ('alajuela', 4), ('limon', 5)) AS campus(nombre, id);
        EXECUTE format('CREATE OR REPLACE VIEW sig.%I AS %s', capa.nombre, union_sql);
        EXECUTE format('REVOKE ALL ON sig.%I FROM PUBLIC', capa.nombre);
    END LOOP;
END;
$$;

-- El propietario NOLOGIN solo puede escribir las tablas originales del nodo.
REVOKE CREATE ON SCHEMA sig FROM sigtec_editor_owner;
GRANT USAGE ON SCHEMA sig TO sigtec_editor_owner;
SELECT format('GRANT USAGE ON SCHEMA %I TO sigtec_editor_owner', nombre)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE id = :campus_id \gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO sigtec_editor_owner',
              nombre)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE id = :campus_id \gexec
SELECT format('GRANT USAGE ON SEQUENCE %I.sigtec_ids TO sigtec_editor_owner', nombre)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE id = :campus_id \gexec

-- Una función sirve a las ocho vistas; el disparador fija el campus autorizado.
-- Los atributos se convierten por el tipo compuesto de la tabla. La geometría
-- se pasa por separado para conservar el tipo PostGIS y su SRID.
CREATE OR REPLACE FUNCTION sig.editar_capa()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    campus smallint;
    tabla text;
    secuencia regclass;
    columnas text;
    atributos text;
    afectadas bigint;
BEGIN
    campus := CASE TG_ARGV[0]
        WHEN 'cartago' THEN 1
        WHEN 'san_jose' THEN 2
        WHEN 'san_carlos' THEN 3
        WHEN 'alajuela' THEN 4
        WHEN 'limon' THEN 5
    END;
    IF campus IS NULL OR TG_TABLE_SCHEMA <> 'sig' OR TG_TABLE_NAME NOT IN
       ('edificios', 'carreteras', 'aceras', 'parqueos', 'zonas_verdes',
        'puntos_interes', 'iluminacion', 'accesibilidad') THEN
        RAISE EXCEPTION 'Campus o capa del disparador inválido';
    END IF;
    tabla := format('%I.%I', TG_ARGV[0], TG_TABLE_NAME);

    IF TG_OP = 'INSERT' THEN
        IF NEW.campus_id IS NOT NULL AND NEW.campus_id <> campus THEN
            RAISE EXCEPTION 'Solo puede insertar % del campus %', TG_TABLE_NAME, campus;
        END IF;
        IF NEW.id IS NOT NULL THEN
            RAISE EXCEPTION 'El id se asigna en el campus de origen';
        END IF;
        secuencia := format('%I.sigtec_ids', TG_ARGV[0])::regclass;
        NEW.id := nextval(secuencia);
        NEW.campus_id := campus;
        SELECT string_agg(format('%I', attname), ', ' ORDER BY attnum)
          INTO columnas
        FROM pg_attribute
        WHERE attrelid = tabla::regclass AND attnum > 0 AND NOT attisdropped
          AND attname <> 'geom';
        EXECUTE format(
            'INSERT INTO %s (%s, geom)
             SELECT %s, $2 FROM jsonb_populate_record(NULL::%s, $1)
             RETURNING *', tabla, columnas, columnas, tabla
        ) INTO NEW USING to_jsonb(NEW) - 'geom', NEW.geom;
        RETURN NEW;
    END IF;

    IF OLD.campus_id <> campus THEN
        RAISE EXCEPTION 'Solo puede editar % de su campus', TG_TABLE_NAME;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.campus_id IS DISTINCT FROM OLD.campus_id THEN
            RAISE EXCEPTION 'El id y el campus_id son inmutables';
        END IF;
        SELECT string_agg(format('%I', attname), ', ' ORDER BY attnum)
          INTO atributos
        FROM pg_attribute
        WHERE attrelid = tabla::regclass AND attnum > 0 AND NOT attisdropped
          AND attname NOT IN ('id', 'campus_id', 'geom');
        EXECUTE format(
            'UPDATE %s SET (%s, geom) =
                (SELECT %s, $2 FROM jsonb_populate_record(NULL::%s, $1))
             WHERE id = $3 RETURNING *',
            tabla, atributos, atributos, tabla
        ) INTO NEW USING to_jsonb(NEW) - 'geom', NEW.geom, OLD.id;
        GET DIAGNOSTICS afectadas = ROW_COUNT;
        IF afectadas <> 1 THEN
            RAISE EXCEPTION 'El objeto ya no existe en el campus de origen';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        EXECUTE format('DELETE FROM %s WHERE id = $1', tabla) USING OLD.id;
        GET DIAGNOSTICS afectadas = ROW_COUNT;
        IF afectadas <> 1 THEN
            RAISE EXCEPTION 'El objeto ya no existe en el campus de origen';
        END IF;
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Operación no admitida: %', TG_OP;
END;
$$;
ALTER FUNCTION sig.editar_capa() OWNER TO sigtec_editor_owner;
REVOKE ALL ON FUNCTION sig.editar_capa() FROM PUBLIC;

SELECT format(
    'CREATE OR REPLACE TRIGGER %I INSTEAD OF INSERT OR UPDATE OR DELETE ON sig.%I
     FOR EACH ROW EXECUTE FUNCTION sig.editar_capa(%L)',
    'editar_' || capa.nombre, capa.nombre, campus.nombre
)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
CROSS JOIN (VALUES ('edificios'), ('carreteras'), ('aceras'), ('parqueos'),
                   ('zonas_verdes'), ('puntos_interes'), ('iluminacion'),
                   ('accesibilidad')) AS capa(nombre)
WHERE campus.id = :campus_id \gexec

-- Reemplaza el disparador de la primera entrega sin perder las filas existentes.
DROP FUNCTION IF EXISTS sig.editar_edificios();

SELECT format('GRANT USAGE ON SCHEMA sig TO %I', 'demo_' || nombre)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE :campus_id IN (0, id) \gexec
SELECT format('GRANT SELECT ON sig.edificios, sig.carreteras, sig.aceras,
              sig.parqueos, sig.zonas_verdes, sig.puntos_interes,
              sig.iluminacion, sig.accesibilidad TO %I', 'demo_' || nombre)
FROM (VALUES ('cartago'), ('san_jose'), ('san_carlos'),
             ('alajuela'), ('limon')) AS campus(nombre)
WHERE :campus_id = 0 \gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON sig.edificios, sig.carreteras,
              sig.aceras, sig.parqueos, sig.zonas_verdes, sig.puntos_interes,
              sig.iluminacion, sig.accesibilidad TO %I', 'demo_' || nombre)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE id = :campus_id \gexec
SELECT format('GRANT SELECT ON public.layer_styles TO %I', 'demo_' || nombre)
FROM (VALUES ('cartago', 1), ('san_jose', 2), ('san_carlos', 3),
             ('alajuela', 4), ('limon', 5)) AS campus(nombre, id)
WHERE :campus_id IN (0, id) \gexec
