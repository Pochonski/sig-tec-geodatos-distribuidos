-- Tabla de estilos con la estructura que crea QGIS 3.44 al guardar un estilo en PostgreSQL.
-- QGIS la busca por base, esquema, vista y columna geométrica.
CREATE TABLE public.layer_styles (
  id serial PRIMARY KEY,
  f_table_catalog varchar,
  f_table_schema varchar,
  f_table_name varchar,
  f_geometry_column varchar,
  stylename text,
  styleqml xml,
  stylesld xml,
  useasdefault boolean,
  description text,
  owner varchar(63) DEFAULT CURRENT_USER,
  ui xml,
  update_time timestamp DEFAULT CURRENT_TIMESTAMP,
  type varchar,
  r_raster_column varchar
);
