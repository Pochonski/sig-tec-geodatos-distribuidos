\set ON_ERROR_STOP on

-- El bootstrap pasa 0 para el central y 1..5 para los campus. El marcador y
-- la fila se crean en la misma transacción; una segunda ejecución no restaura
-- objetos borrados ni sobrescribe ediciones hechas desde QGIS.
SELECT set_config('sigtec.campus_id', :'campus_id', false);

DO $$
DECLARE
    campus smallint := current_setting('sigtec.campus_id')::smallint;
    esquema text;
    nombre_campus text;
    codigo_campus text;
    longitud double precision;
    latitud double precision;
    centro geometry;
    x double precision;
    y double precision;
    capa record;
    nuevo_id bigint;
    insertadas bigint;
    geom geometry;
BEGIN
    IF campus BETWEEN 1 AND 5 THEN
        SELECT c.esquema, c.nombre, c.codigo, c.longitud, c.latitud
          INTO esquema, nombre_campus, codigo_campus, longitud, latitud
        FROM (VALUES
            (1, 'cartago', 'Cartago', 'CT', -83.910::double precision, 9.848::double precision),
            (2, 'san_jose', 'San José', 'SJ', -84.072::double precision, 9.929::double precision),
            (3, 'san_carlos', 'San Carlos', 'SC', -84.516::double precision, 10.359::double precision),
            (4, 'alajuela', 'Alajuela', 'AL', -84.210::double precision, 10.015::double precision),
            (5, 'limon', 'Limón', 'LI', -83.035::double precision, 10.003::double precision)
        ) AS c(id, esquema, nombre, codigo, longitud, latitud)
        WHERE c.id = campus;

        -- Los puntos de partida están en WGS84 y se transforman al SRID 8908.
        centro := ST_Transform(ST_SetSRID(ST_MakePoint(longitud, latitud), 4326), 8908);
        x := ST_X(centro);
        y := ST_Y(centro);

        FOR capa IN
            SELECT * FROM (VALUES
                (1, 'edificios'), (2, 'carreteras'), (3, 'aceras'),
                (4, 'parqueos'), (5, 'zonas_verdes'), (6, 'puntos_interes'),
                (7, 'iluminacion'), (8, 'accesibilidad')
            ) AS c(orden, nombre) ORDER BY orden
        LOOP
            INSERT INTO sig.seed_aplicada (nombre)
            VALUES (esquema || '.' || capa.nombre)
            ON CONFLICT DO NOTHING;
            GET DIAGNOSTICS insertadas = ROW_COUNT;
            IF insertadas = 0 THEN
                CONTINUE;
            END IF;

            nuevo_id := nextval(format('%I.sigtec_ids', esquema)::regclass);
            IF capa.nombre = 'edificios' THEN
                geom := ST_MakeEnvelope(x, y, x + 30, y + 20, 8908);
                EXECUTE format(
                    'INSERT INTO %I.edificios
                     (id, campus_id, nombre, codigo, area, pisos, geom)
                     VALUES ($1, $2, $3, $4, $5, $6, $7)', esquema
                ) USING nuevo_id, campus, 'Edificio ficticio de ' || nombre_campus,
                        codigo_campus || '-ED-PRUEBA', 600.0, 2, geom;
            ELSIF capa.nombre = 'carreteras' THEN
                geom := ST_MakeLine(
                    ST_SetSRID(ST_MakePoint(x - 20, y - 25), 8908),
                    ST_SetSRID(ST_MakePoint(x + 45, y - 25), 8908)
                );
                EXECUTE format(
                    'INSERT INTO %I.carreteras
                     (id, campus_id, nombre, tipo, superficie, geom)
                     VALUES ($1, $2, $3, $4, $5, $6)', esquema
                ) USING nuevo_id, campus, 'Vía ficticia de ' || nombre_campus,
                        'interna', 'asfalto', geom;
            ELSIF capa.nombre = 'aceras' THEN
                geom := ST_MakeLine(
                    ST_SetSRID(ST_MakePoint(x - 20, y - 18), 8908),
                    ST_SetSRID(ST_MakePoint(x + 45, y - 18), 8908)
                );
                EXECUTE format(
                    'INSERT INTO %I.aceras
                     (id, campus_id, material, ancho, condicion, geom)
                     VALUES ($1, $2, $3, $4, $5, $6)', esquema
                ) USING nuevo_id, campus, 'concreto', 1.8, 'buena', geom;
            ELSIF capa.nombre = 'parqueos' THEN
                geom := ST_MakeEnvelope(x + 40, y, x + 75, y + 25, 8908);
                EXECUTE format(
                    'INSERT INTO %I.parqueos
                     (id, campus_id, capacidad, tipo, disponibilidad, geom)
                     VALUES ($1, $2, $3, $4, $5, $6)', esquema
                ) USING nuevo_id, campus, 30, 'general', true, geom;
            ELSIF capa.nombre = 'zonas_verdes' THEN
                geom := ST_MakeEnvelope(x - 45, y + 25, x - 10, y + 45, 8908);
                EXECUTE format(
                    'INSERT INTO %I.zonas_verdes
                     (id, campus_id, area, tipo_vegetacion, geom)
                     VALUES ($1, $2, $3, $4, $5)', esquema
                ) USING nuevo_id, campus, 700.0, 'césped y árboles', geom;
            ELSIF capa.nombre = 'puntos_interes' THEN
                geom := ST_SetSRID(ST_MakePoint(x + 15, y + 10), 8908);
                EXECUTE format(
                    'INSERT INTO %I.puntos_interes
                     (id, campus_id, nombre, tipo, geom)
                     VALUES ($1, $2, $3, $4, $5)', esquema
                ) USING nuevo_id, campus, 'Soda ficticia de ' || nombre_campus,
                        'soda', geom;
            ELSIF capa.nombre = 'iluminacion' THEN
                geom := ST_SetSRID(ST_MakePoint(x + 35, y - 15), 8908);
                EXECUTE format(
                    'INSERT INTO %I.iluminacion
                     (id, campus_id, codigo, potencia, estado, geom)
                     VALUES ($1, $2, $3, $4, $5, $6)', esquema
                ) USING nuevo_id, campus, codigo_campus || '-IL-PRUEBA',
                        80.0, 'operativa', geom;
            ELSIF capa.nombre = 'accesibilidad' THEN
                geom := ST_MakeLine(
                    ST_SetSRID(ST_MakePoint(x + 5, y - 5), 8908),
                    ST_SetSRID(ST_MakePoint(x + 5, y + 10), 8908)
                );
                EXECUTE format(
                    'INSERT INTO %I.accesibilidad
                     (id, campus_id, tipo, geom)
                     VALUES ($1, $2, $3, $4)', esquema
                ) USING nuevo_id, campus, 'rampa', geom;
            END IF;
        END LOOP;
    END IF;
END;
$$;
