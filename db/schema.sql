\set ON_ERROR_STOP on
\getenv cartago_password SIGTEC_CARTAGO_PASSWORD
\getenv san_carlos_password SIGTEC_SAN_CARLOS_PASSWORD
\getenv replication_password SIGTEC_REPLICATION_PASSWORD

CREATE EXTENSION IF NOT EXISTS postgis;

SELECT 'CREATE ROLE demo_cartago LOGIN' WHERE :'node' IN ('central', 'cartago')
  AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'demo_cartago') \gexec
SELECT 'CREATE ROLE demo_san_carlos LOGIN' WHERE :'node' IN ('central', 'san_carlos')
  AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'demo_san_carlos') \gexec
SELECT 'CREATE ROLE sigtec_repl LOGIN REPLICATION'
  WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sigtec_repl') \gexec
SELECT 'CREATE ROLE sigtec_editor_owner NOLOGIN'
  WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sigtec_editor_owner') \gexec
SELECT 'CREATE ROLE sigtec_auth_owner NOLOGIN'
  WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sigtec_auth_owner') \gexec

SELECT format('ALTER ROLE demo_cartago PASSWORD %L', :'cartago_password')
  WHERE :'node' IN ('central', 'cartago') \gexec
SELECT format('ALTER ROLE demo_san_carlos PASSWORD %L', :'san_carlos_password')
  WHERE :'node' IN ('central', 'san_carlos') \gexec
SELECT format('ALTER ROLE sigtec_repl PASSWORD %L', :'replication_password') \gexec

REVOKE CONNECT ON DATABASE sig_tec FROM PUBLIC;
GRANT CONNECT ON DATABASE sig_tec TO sigtec_repl;
SELECT 'GRANT CONNECT ON DATABASE sig_tec TO demo_cartago'
  WHERE :'node' IN ('central', 'cartago') \gexec
SELECT 'GRANT CONNECT ON DATABASE sig_tec TO demo_san_carlos'
  WHERE :'node' IN ('central', 'san_carlos') \gexec

CREATE SCHEMA IF NOT EXISTS cartago;
CREATE SCHEMA IF NOT EXISTS san_carlos;
CREATE SCHEMA IF NOT EXISTS sig;
CREATE SCHEMA IF NOT EXISTS auth;
REVOKE ALL ON SCHEMA cartago, san_carlos, sig, auth FROM PUBLIC;

CREATE TABLE IF NOT EXISTS cartago.edificios (
    id bigint PRIMARY KEY,
    campus_id smallint NOT NULL DEFAULT 1 CHECK (campus_id = 1),
    nombre text NOT NULL,
    codigo text,
    area double precision,
    pisos integer,
    geom geometry(Polygon, 8908) NOT NULL
);
CREATE TABLE IF NOT EXISTS san_carlos.edificios (
    id bigint PRIMARY KEY,
    campus_id smallint NOT NULL DEFAULT 3 CHECK (campus_id = 3),
    nombre text NOT NULL,
    codigo text,
    area double precision,
    pisos integer,
    geom geometry(Polygon, 8908) NOT NULL
);
REVOKE ALL ON cartago.edificios, san_carlos.edificios FROM PUBLIC;
CREATE INDEX IF NOT EXISTS cartago_edificios_geom_idx ON cartago.edificios USING gist (geom);
CREATE INDEX IF NOT EXISTS san_carlos_edificios_geom_idx ON san_carlos.edificios USING gist (geom);

SELECT 'CREATE SEQUENCE IF NOT EXISTS cartago.sigtec_ids AS bigint START WITH 1 INCREMENT BY 5'
  WHERE :'node' = 'cartago' \gexec
SELECT 'CREATE SEQUENCE IF NOT EXISTS san_carlos.sigtec_ids AS bigint START WITH 3 INCREMENT BY 5'
  WHERE :'node' = 'san_carlos' \gexec

CREATE TABLE IF NOT EXISTS sig.seed_aplicada (nombre text PRIMARY KEY);
REVOKE ALL ON sig.seed_aplicada FROM PUBLIC;

-- Match the layer_styles definition created by QGIS 3.44.
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
GRANT SELECT ON cartago.edificios, san_carlos.edificios, public.layer_styles TO sigtec_repl;
GRANT USAGE ON SCHEMA cartago, san_carlos TO sigtec_repl;

CREATE TABLE IF NOT EXISTS auth.cuentas (
    usuario name PRIMARY KEY,
    campus_id smallint NOT NULL CHECK (campus_id IN (1, 3))
);
REVOKE ALL ON auth.cuentas FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA auth TO sigtec_auth_owner;
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
SELECT 'GRANT USAGE ON SCHEMA auth TO demo_cartago, demo_san_carlos'
  WHERE :'node' = 'central' \gexec
SELECT 'GRANT EXECUTE ON FUNCTION auth.mi_campus() TO demo_cartago, demo_san_carlos'
  WHERE :'node' = 'central' \gexec
INSERT INTO auth.cuentas (usuario, campus_id)
SELECT 'demo_cartago', 1 WHERE :'node' = 'central'
ON CONFLICT (usuario) DO UPDATE SET campus_id = EXCLUDED.campus_id;
INSERT INTO auth.cuentas (usuario, campus_id)
SELECT 'demo_san_carlos', 3 WHERE :'node' = 'central'
ON CONFLICT (usuario) DO UPDATE SET campus_id = EXCLUDED.campus_id;

CREATE OR REPLACE VIEW sig.edificios AS
SELECT id, campus_id, nombre, codigo, area, pisos, geom::geometry(Polygon, 8908) AS geom
FROM cartago.edificios
UNION ALL
SELECT id, campus_id, nombre, codigo, area, pisos, geom::geometry(Polygon, 8908) AS geom
FROM san_carlos.edificios;
REVOKE ALL ON sig.edificios FROM PUBLIC;

-- Only the local campus table is writable by the function owner.
GRANT USAGE, CREATE ON SCHEMA sig TO sigtec_editor_owner;
SELECT 'GRANT USAGE ON SCHEMA cartago TO sigtec_editor_owner'
  WHERE :'node' = 'cartago' \gexec
SELECT 'GRANT USAGE ON SCHEMA san_carlos TO sigtec_editor_owner'
  WHERE :'node' = 'san_carlos' \gexec
SELECT 'GRANT SELECT, INSERT, UPDATE, DELETE ON cartago.edificios TO sigtec_editor_owner'
  WHERE :'node' = 'cartago' \gexec
SELECT 'GRANT SELECT, INSERT, UPDATE, DELETE ON san_carlos.edificios TO sigtec_editor_owner'
  WHERE :'node' = 'san_carlos' \gexec
SELECT 'GRANT USAGE ON SEQUENCE cartago.sigtec_ids TO sigtec_editor_owner'
  WHERE :'node' = 'cartago' \gexec
SELECT 'GRANT USAGE ON SEQUENCE san_carlos.sigtec_ids TO sigtec_editor_owner'
  WHERE :'node' = 'san_carlos' \gexec

CREATE OR REPLACE FUNCTION sig.editar_edificios()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    campus smallint;
    tabla text;
    secuencia regclass;
    afectadas bigint;
BEGIN
    IF TG_ARGV[0] = 'cartago' THEN
        campus := 1;
        tabla := 'cartago.edificios';
        secuencia := 'cartago.sigtec_ids'::regclass;
    ELSIF TG_ARGV[0] = 'san_carlos' THEN
        campus := 3;
        tabla := 'san_carlos.edificios';
        secuencia := 'san_carlos.sigtec_ids'::regclass;
    ELSE
        RAISE EXCEPTION 'Campus del disparador inválido';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.campus_id IS NOT NULL AND NEW.campus_id <> campus THEN
            RAISE EXCEPTION 'Solo puede insertar edificios del campus %', campus;
        END IF;
        IF NEW.id IS NOT NULL THEN
            RAISE EXCEPTION 'El id se asigna en el campus de origen';
        END IF;
        NEW.id := nextval(secuencia);
        NEW.campus_id := campus;
        EXECUTE format('INSERT INTO %s (id, campus_id, nombre, codigo, area, pisos, geom)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        RETURNING id, campus_id, nombre, codigo, area, pisos, geom', tabla)
        INTO NEW
        USING NEW.id, NEW.campus_id, NEW.nombre, NEW.codigo, NEW.area, NEW.pisos, NEW.geom;
        RETURN NEW;
    END IF;

    IF OLD.campus_id <> campus THEN
        RAISE EXCEPTION 'Solo puede editar edificios de su campus';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.campus_id IS DISTINCT FROM OLD.campus_id THEN
            RAISE EXCEPTION 'El id y el campus_id son inmutables';
        END IF;
        EXECUTE format('UPDATE %s
                        SET nombre = $1, codigo = $2, area = $3, pisos = $4, geom = $5
                        WHERE id = $6
                        RETURNING id, campus_id, nombre, codigo, area, pisos, geom', tabla)
        INTO NEW
        USING NEW.nombre, NEW.codigo, NEW.area, NEW.pisos, NEW.geom, OLD.id;
        GET DIAGNOSTICS afectadas = ROW_COUNT;
        IF afectadas <> 1 THEN
            RAISE EXCEPTION 'El edificio ya no existe en el campus de origen';
        END IF;
        RETURN NEW;
    END IF;

    EXECUTE format('DELETE FROM %s WHERE id = $1', tabla) USING OLD.id;
    GET DIAGNOSTICS afectadas = ROW_COUNT;
    IF afectadas <> 1 THEN
        RAISE EXCEPTION 'El edificio ya no existe en el campus de origen';
    END IF;
    RETURN OLD;
END;
$$;
ALTER FUNCTION sig.editar_edificios() OWNER TO sigtec_editor_owner;
REVOKE ALL ON FUNCTION sig.editar_edificios() FROM PUBLIC;

SELECT 'CREATE OR REPLACE TRIGGER editar_edificios
        INSTEAD OF INSERT OR UPDATE OR DELETE ON sig.edificios
        FOR EACH ROW EXECUTE FUNCTION sig.editar_edificios(''cartago'')'
  WHERE :'node' = 'cartago' \gexec
SELECT 'CREATE OR REPLACE TRIGGER editar_edificios
        INSTEAD OF INSERT OR UPDATE OR DELETE ON sig.edificios
        FOR EACH ROW EXECUTE FUNCTION sig.editar_edificios(''san_carlos'')'
  WHERE :'node' = 'san_carlos' \gexec

SELECT 'GRANT USAGE ON SCHEMA sig TO demo_cartago'
  WHERE :'node' = 'cartago' \gexec
SELECT 'GRANT SELECT, INSERT, UPDATE, DELETE ON sig.edificios TO demo_cartago'
  WHERE :'node' = 'cartago' \gexec
SELECT 'GRANT SELECT ON public.layer_styles TO demo_cartago'
  WHERE :'node' = 'cartago' \gexec
SELECT 'GRANT USAGE ON SCHEMA sig TO demo_san_carlos'
  WHERE :'node' = 'san_carlos' \gexec
SELECT 'GRANT SELECT, INSERT, UPDATE, DELETE ON sig.edificios TO demo_san_carlos'
  WHERE :'node' = 'san_carlos' \gexec
SELECT 'GRANT SELECT ON public.layer_styles TO demo_san_carlos'
  WHERE :'node' = 'san_carlos' \gexec
