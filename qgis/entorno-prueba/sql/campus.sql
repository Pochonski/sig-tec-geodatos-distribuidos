-- Campus simulado para el complemento de QGIS.
-- Variables de psql: campus_id, usuario_prueba, clave_prueba, suscripcion y conexion_central.
-- Los cinco esquemas existen en el nodo; solo el del campus local es editable mediante las vistas sig.

CREATE ROLE sig_usuario NOLOGIN;
CREATE ROLE sig_editor_local NOLOGIN;
REVOKE CONNECT, TEMPORARY ON DATABASE sig_tec FROM PUBLIC;
GRANT CONNECT ON DATABASE sig_tec TO sig_usuario;

CREATE SCHEMA sig;
GRANT USAGE ON SCHEMA sig TO sig_usuario, sig_editor_local;

CREATE TABLE sig.campus (
  campus_id smallint PRIMARY KEY,
  esquema name NOT NULL UNIQUE,
  nombre text NOT NULL
);
INSERT INTO sig.campus VALUES
  (1, 'cartago', 'Cartago'),
  (2, 'san_jose', 'San José'),
  (3, 'san_carlos', 'San Carlos'),
  (4, 'alajuela', 'Alajuela'),
  (5, 'limon', 'Limón');

-- Una sola fila con el campus que administra este nodo.
CREATE TABLE sig.nodo (
  campus_id smallint PRIMARY KEY REFERENCES sig.campus,
  unico boolean NOT NULL DEFAULT true UNIQUE CHECK (unico)
);
INSERT INTO sig.nodo (campus_id) VALUES (:campus_id);
GRANT SELECT ON sig.campus, sig.nodo TO sig_usuario, sig_editor_local;

CREATE FUNCTION sig.campus_local() RETURNS smallint
  LANGUAGE sql STABLE
  SET search_path = pg_catalog, pg_temp
AS $$
  SELECT n.campus_id FROM sig.nodo n
$$;

-- Diccionario de capas de docs/diseno.md.
CREATE TEMP TABLE capas (capa name, geometria text, atributos text, posicion int);
INSERT INTO capas VALUES
  ('edificios', 'Polygon', 'nombre text, codigo text, area numeric(12, 2), pisos integer', 1),
  ('carreteras', 'LineString', 'nombre text, tipo text, superficie text', 2),
  ('aceras', 'LineString', 'material text, condicion text, ancho numeric(6, 2)', 3),
  ('parqueos', 'Polygon', 'capacidad integer, tipo text, disponibilidad boolean', 4),
  ('zonas_verdes', 'Polygon', 'area numeric(12, 2), tipo_vegetacion text', 5),
  ('puntos_interes', 'Point', 'nombre text, tipo text', 6),
  ('iluminacion', 'Point', 'codigo text, estado text, potencia numeric(8, 2)', 7),
  ('accesibilidad', 'LineString', 'tipo text', 8);

DO $$
DECLARE
  k record;
  c record;
  v_local name;
BEGIN
  SELECT esquema INTO STRICT v_local FROM sig.campus WHERE campus_id = sig.campus_local();

  FOR k IN SELECT campus_id, esquema FROM sig.campus ORDER BY campus_id LOOP
    EXECUTE format('CREATE SCHEMA %I', k.esquema);
    FOR c IN SELECT * FROM capas ORDER BY posicion LOOP
      EXECUTE format(
        'CREATE TABLE %I.%I (id bigint PRIMARY KEY, campus_id smallint NOT NULL CHECK (campus_id = %s), %s, geom geometry(%s, 8908) NOT NULL)',
        k.esquema, c.capa, k.campus_id, c.atributos, c.geometria);
    END LOOP;
  END LOOP;

  -- Secuencia compartida por las ocho tablas del campus: campus_id, campus_id + 5, ...
  EXECUTE format('CREATE SEQUENCE %I.id_seq AS bigint START %s INCREMENT 5 MINVALUE %s',
    v_local, sig.campus_local(), sig.campus_local());
  EXECUTE format('GRANT USAGE ON SCHEMA %I TO sig_editor_local', v_local);
  EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO sig_editor_local', v_local);
  EXECUTE format('GRANT USAGE ON SEQUENCE %I.id_seq TO sig_editor_local', v_local);
END
$$;

-- Escribe en la tabla original del campus local y rechaza cualquier fila de otro campus.
CREATE FUNCTION sig.editar_capa() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER
  SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_local smallint := sig.campus_local();
  v_esquema name;
  v_tabla regclass;
  v_asignaciones text;
  v_filas bigint;
BEGIN
  SELECT c.esquema INTO STRICT v_esquema FROM sig.campus c WHERE c.campus_id = v_local;
  v_tabla := format('%I.%I', v_esquema, TG_TABLE_NAME)::regclass;

  IF TG_OP = 'INSERT' THEN
    IF NEW.campus_id IS NOT NULL AND NEW.campus_id <> v_local THEN
      RAISE EXCEPTION 'SIG-TEC: no se puede crear un objeto del campus % en sig.%; este nodo solo crea objetos del campus %',
        NEW.campus_id, TG_TABLE_NAME, v_local
        USING ERRCODE = 'insufficient_privilege';
    END IF;
    NEW.id := nextval(format('%I.id_seq', v_esquema)::regclass);
    NEW.campus_id := v_local;
    EXECUTE format('INSERT INTO %s SELECT ($1).*', v_tabla) USING NEW;
    RETURN NEW;
  END IF;

  IF OLD.campus_id <> v_local THEN
    RAISE EXCEPTION 'SIG-TEC: el objeto % de sig.% pertenece al campus %; este nodo solo modifica objetos del campus %',
      OLD.id, TG_TABLE_NAME, OLD.campus_id, v_local
      USING ERRCODE = 'insufficient_privilege',
            HINT = 'Solicite el cambio al campus propietario.';
  END IF;

  IF TG_OP = 'DELETE' THEN
    EXECUTE format('DELETE FROM %s WHERE id = $1', v_tabla) USING OLD.id;
    GET DIAGNOSTICS v_filas = ROW_COUNT;
    RETURN CASE WHEN v_filas = 0 THEN NULL ELSE OLD END;
  END IF;

  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.campus_id IS DISTINCT FROM OLD.campus_id THEN
    RAISE EXCEPTION 'SIG-TEC: no se puede cambiar id ni campus_id del objeto % de sig.%', OLD.id, TG_TABLE_NAME
      USING ERRCODE = 'insufficient_privilege';
  END IF;

  SELECT string_agg(format('%1$I = ($1).%1$I', a.attname), ', ' ORDER BY a.attnum)
    INTO v_asignaciones
    FROM pg_attribute a
   WHERE a.attrelid = v_tabla AND a.attnum > 0 AND NOT a.attisdropped
     AND a.attname NOT IN ('id', 'campus_id');
  EXECUTE format('UPDATE %s SET %s WHERE id = $2', v_tabla, v_asignaciones) USING NEW, OLD.id;
  GET DIAGNOSTICS v_filas = ROW_COUNT;
  RETURN CASE WHEN v_filas = 0 THEN NULL ELSE NEW END;
END
$$;
ALTER FUNCTION sig.editar_capa() OWNER TO sig_editor_local;
REVOKE ALL ON FUNCTION sig.editar_capa() FROM PUBLIC;

-- Una vista por capa con los cinco campus; QGIS la carga con id como clave y geom como geometría.
DO $$
DECLARE
  c record;
  v_columnas text;
  v_consulta text;
BEGIN
  FOR c IN SELECT capa FROM capas ORDER BY posicion LOOP
    SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum)
      INTO v_columnas
      FROM pg_attribute a
     WHERE a.attrelid = format('cartago.%I', c.capa)::regclass AND a.attnum > 0 AND NOT a.attisdropped;
    SELECT string_agg(format('SELECT %s FROM %I.%I', v_columnas, esquema, c.capa), ' UNION ALL ' ORDER BY campus_id)
      INTO v_consulta
      FROM sig.campus;

    EXECUTE format('CREATE VIEW sig.%I AS %s', c.capa, v_consulta);
    EXECUTE format('ALTER VIEW sig.%I ALTER COLUMN campus_id SET DEFAULT sig.campus_local()', c.capa);
    EXECUTE format('CREATE TRIGGER editar INSTEAD OF INSERT OR UPDATE OR DELETE ON sig.%I FOR EACH ROW EXECUTE FUNCTION sig.editar_capa()', c.capa);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON sig.%I TO sig_usuario', c.capa);
  END LOOP;
END
$$;

-- Un objeto ficticio por capa y campus. Las coordenadas son aproximadas y solo ubican cada campus.
CREATE TEMP TABLE semilla (campus_id smallint, sigla text, lon float8, lat float8);
INSERT INTO semilla VALUES
  (1, 'CA', -83.9125, 9.8556),
  (2, 'SJ', -84.0752, 9.9378),
  (3, 'SC', -84.5122, 10.3633),
  (4, 'AL', -84.2131, 10.0159),
  (5, 'LI', -83.0306, 9.9925);

DO $$
DECLARE
  s record;
  x float8;
  y float8;
  i bigint;
  e name;
BEGIN
  FOR s IN SELECT c.esquema, c.nombre, m.* FROM semilla m JOIN sig.campus c USING (campus_id) LOOP
    SELECT ST_X(p), ST_Y(p) INTO x, y
      FROM ST_Transform(ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), 8908) AS p;
    i := s.campus_id;
    e := s.esquema;

    EXECUTE format('INSERT INTO %I.edificios VALUES ($1, $2, $3, $4, 1000, 3, ST_MakeEnvelope($5, $6, $5 + 40, $6 + 25, 8908))', e)
      USING i, s.campus_id, 'Edificio de aulas ' || s.nombre, s.sigla || '-A1', x, y;
    EXECUTE format('INSERT INTO %I.carreteras VALUES ($1, $2, $3, ''interna'', ''asfalto'', ST_SetSRID(ST_MakeLine(ST_MakePoint($4 - 60, $5 - 20), ST_MakePoint($4 + 120, $5 - 20)), 8908))', e)
      USING i + 5, s.campus_id, 'Calle principal ' || s.nombre, x, y;
    EXECUTE format('INSERT INTO %I.aceras VALUES ($1, $2, ''concreto'', ''buena'', 1.5, ST_SetSRID(ST_MakeLine(ST_MakePoint($3 - 60, $4 - 14), ST_MakePoint($3 + 120, $4 - 14)), 8908))', e)
      USING i + 10, s.campus_id, x, y;
    EXECUTE format('INSERT INTO %I.parqueos VALUES ($1, $2, 40, ''general'', true, ST_MakeEnvelope($3 + 50, $4, $3 + 90, $4 + 30, 8908))', e)
      USING i + 15, s.campus_id, x, y;
    EXECUTE format('INSERT INTO %I.zonas_verdes VALUES ($1, $2, 2400, ''césped arbolado'', ST_MakeEnvelope($3, $4 + 35, $3 + 60, $4 + 75, 8908))', e)
      USING i + 20, s.campus_id, x, y;
    EXECUTE format('INSERT INTO %I.puntos_interes VALUES ($1, $2, $3, ''servicio'', ST_SetSRID(ST_MakePoint($4 + 20, $5 + 30), 8908))', e)
      USING i + 25, s.campus_id, 'Biblioteca ' || s.nombre, x, y;
    EXECUTE format('INSERT INTO %I.iluminacion VALUES ($1, $2, $3, $4, 150, ST_SetSRID(ST_MakePoint($5 + 45, $6 - 17), 8908))', e)
      USING i + 30, s.campus_id, 'L-' || s.sigla || '-001',
            CASE s.campus_id WHEN 2 THEN 'averiada' WHEN 4 THEN 'mantenimiento' ELSE 'funcional' END, x, y;
    EXECUTE format('INSERT INTO %I.accesibilidad VALUES ($1, $2, ''rampa'', ST_SetSRID(ST_MakeLine(ST_MakePoint($3 + 20, $4 - 14), ST_MakePoint($3 + 20, $4)), 8908))', e)
      USING i + 35, s.campus_id, x, y;
  END LOOP;

  -- La semilla usó los ocho primeros valores de la secuencia local.
  SELECT esquema INTO STRICT e FROM sig.campus WHERE campus_id = sig.campus_local();
  PERFORM setval(format('%I.id_seq', e)::regclass, sig.campus_local() + 35);
END
$$;

CREATE ROLE :"usuario_prueba" LOGIN PASSWORD :'clave_prueba' IN ROLE sig_usuario;

-- Los estilos llegan del central; las cuentas del campus solo pueden leerlos.
\ir layer_styles.sql
GRANT SELECT ON public.layer_styles TO sig_usuario;
CREATE SUBSCRIPTION :"suscripcion" CONNECTION :'conexion_central' PUBLICATION estilos;
