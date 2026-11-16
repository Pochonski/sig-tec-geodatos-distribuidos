-- Prueba de inventario, edición local y aislamiento con una cuenta de campus.
-- Se ejecuta dentro de una transacción que se revierte, así que no deja cambios.
\set ON_ERROR_STOP on
BEGIN;

DO $$
DECLARE
  v_local smallint := sig.campus_local();
  v_capa text;
  v_total bigint;
  v_id bigint;
  v_campus smallint;
  v_ajeno bigint;
  v_antes text;
  v_despues text;
BEGIN
  -- Inventario: cinco objetos por vista, geometrías válidas en SRID 8908.
  FOREACH v_capa IN ARRAY ARRAY['edificios', 'carreteras', 'aceras', 'parqueos', 'zonas_verdes',
                                 'puntos_interes', 'iluminacion', 'accesibilidad'] LOOP
    EXECUTE format('SELECT count(*) FROM sig.%I WHERE ST_IsValid(geom) AND ST_SRID(geom) = 8908 AND (id - campus_id) %% 5 = 0', v_capa)
      INTO v_total;
    ASSERT v_total = 5, format('sig.%s tiene %s objetos válidos; se esperaban 5', v_capa, v_total);
  END LOOP;
  RAISE NOTICE 'ok: inventario de 8 vistas con 5 objetos cada una';

  -- Edición local: insertar, actualizar atributos y geometría, eliminar.
  INSERT INTO sig.edificios (nombre, codigo, area, pisos, geom)
  SELECT 'Edificio de prueba', 'T-1', 100, 1, ST_Translate(geom, 0, 200) FROM sig.edificios WHERE campus_id = v_local
  RETURNING id, campus_id INTO v_id, v_campus;
  ASSERT v_campus = v_local AND (v_id - v_local) % 5 = 0, format('id %s o campus %s inesperados', v_id, v_campus);
  ASSERT (SELECT count(*) FROM sig.edificios WHERE id = v_id) = 1, 'la vista no muestra exactamente un objeto nuevo';

  UPDATE sig.edificios SET nombre = 'Edificio renombrado', geom = ST_Translate(geom, 5, 5) WHERE id = v_id;
  ASSERT (SELECT nombre FROM sig.edificios WHERE id = v_id) = 'Edificio renombrado', 'no se actualizó el objeto propio';

  DELETE FROM sig.edificios WHERE id = v_id;
  ASSERT NOT EXISTS (SELECT FROM sig.edificios WHERE id = v_id), 'no se eliminó el objeto propio';
  RAISE NOTICE 'ok: insertar, actualizar y eliminar un edificio propio (id %)', v_id;

  -- Aislamiento: cada intento debe fallar con insufficient_privilege.
  SELECT id INTO STRICT v_ajeno FROM sig.edificios WHERE campus_id <> v_local ORDER BY id LIMIT 1;
  SELECT string_agg(e::text, '|' ORDER BY id) INTO v_antes FROM sig.edificios e;

  BEGIN
    UPDATE sig.edificios SET nombre = 'Intrusión' WHERE id = v_ajeno;
    RAISE EXCEPTION 'FALLO: se actualizó el objeto ajeno %', v_ajeno;
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'ok: actualizar objeto ajeno rechazado (%)', SQLERRM;
  END;

  BEGIN
    DELETE FROM sig.edificios WHERE id = v_ajeno;
    RAISE EXCEPTION 'FALLO: se eliminó el objeto ajeno %', v_ajeno;
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'ok: eliminar objeto ajeno rechazado';
  END;

  BEGIN
    INSERT INTO sig.edificios (campus_id, nombre, geom)
    SELECT CASE v_local WHEN 1 THEN 3 ELSE 1 END, 'Ajeno', geom FROM sig.edificios WHERE id = v_ajeno;
    RAISE EXCEPTION 'FALLO: se insertó un objeto con campus_id ajeno';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'ok: insertar con campus_id ajeno rechazado';
  END;

  BEGIN
    UPDATE sig.edificios SET campus_id = CASE v_local WHEN 1 THEN 3 ELSE 1 END WHERE campus_id = v_local;
    RAISE EXCEPTION 'FALLO: se cambió el campus_id de un objeto propio';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'ok: cambiar campus_id rechazado';
  END;

  BEGIN
    EXECUTE format('DELETE FROM %I.edificios', (SELECT esquema FROM sig.campus WHERE campus_id = v_local));
    RAISE EXCEPTION 'FALLO: se escribió directamente en la tabla física';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'ok: escritura directa en la tabla física rechazada';
  END;

  BEGIN
    DELETE FROM public.layer_styles;
    RAISE EXCEPTION 'FALLO: se modificó layer_styles desde el campus';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'ok: escritura en layer_styles rechazada';
  END;

  SELECT string_agg(e::text, '|' ORDER BY id) INTO v_despues FROM sig.edificios e;
  ASSERT v_antes = v_despues, 'los edificios cambiaron después de los intentos rechazados';
  RAISE NOTICE 'ok: los registros quedan iguales después de los intentos rechazados';
END
$$;

ROLLBACK;
