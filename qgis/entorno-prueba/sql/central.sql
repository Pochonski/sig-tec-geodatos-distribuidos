-- Central simulado para el complemento de QGIS.
-- Variables de psql: clave_prueba y clave_replicador.

CREATE ROLE sig_usuario NOLOGIN;
CREATE ROLE auth_lector NOLOGIN;
REVOKE CONNECT, TEMPORARY ON DATABASE sig_tec FROM PUBLIC;
GRANT CONNECT ON DATABASE sig_tec TO sig_usuario;

CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA auth TO auth_lector, sig_usuario;

CREATE TABLE auth.campus (
  campus_id smallint PRIMARY KEY,
  nombre text NOT NULL
);
INSERT INTO auth.campus VALUES
  (1, 'Cartago'), (2, 'San José'), (3, 'San Carlos'), (4, 'Alajuela'), (5, 'Limón');

-- Solo la administración registra asignaciones; las cuentas consultan la suya con auth.mi_campus().
CREATE TABLE auth.asignaciones (
  usuario name PRIMARY KEY,
  campus_id smallint NOT NULL REFERENCES auth.campus
);
GRANT SELECT ON auth.asignaciones TO auth_lector;

CREATE FUNCTION auth.mi_campus() RETURNS smallint
  LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = pg_catalog, pg_temp
AS $$
  SELECT a.campus_id FROM auth.asignaciones a WHERE a.usuario = session_user
$$;
ALTER FUNCTION auth.mi_campus() OWNER TO auth_lector;
REVOKE ALL ON FUNCTION auth.mi_campus() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth.mi_campus() TO sig_usuario;

CREATE ROLE cartago_prueba LOGIN PASSWORD :'clave_prueba' IN ROLE sig_usuario;
CREATE ROLE san_jose_prueba LOGIN PASSWORD :'clave_prueba' IN ROLE sig_usuario;
CREATE ROLE san_carlos_prueba LOGIN PASSWORD :'clave_prueba' IN ROLE sig_usuario;
CREATE ROLE sin_campus_prueba LOGIN PASSWORD :'clave_prueba' IN ROLE sig_usuario;
INSERT INTO auth.asignaciones VALUES ('cartago_prueba', 1), ('san_jose_prueba', 2), ('san_carlos_prueba', 3);

-- Los estilos institucionales se definen aquí y se replican a los campus.
\ir layer_styles.sql
GRANT SELECT ON public.layer_styles TO sig_usuario;

CREATE ROLE replicador LOGIN REPLICATION PASSWORD :'clave_replicador';
GRANT CONNECT ON DATABASE sig_tec TO replicador;
GRANT SELECT ON public.layer_styles TO replicador;
CREATE PUBLICATION estilos FOR TABLE public.layer_styles;
