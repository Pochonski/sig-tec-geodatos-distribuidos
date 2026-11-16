"""Genera el SQL que publica los estilos QML de SIG-TEC en public.layer_styles del central.

El central replica la tabla a los campus. Al terminar, cada vista tiene exactamente una fila
SIG-TEC y es su único estilo predeterminado, aunque antes hubiera duplicados. Ejemplo:

    python qgis/herramientas/publicar_estilos.py | docker compose -f qgis/entorno-prueba/compose.yaml \
        exec -T central psql -U postgres -d sig_tec -v ON_ERROR_STOP=1
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sig_tec.configuracion import (  # noqa: E402
    BASE_DATOS,
    CAPAS,
    COLUMNA_GEOMETRIA,
    DIRECTORIO_ESTILOS,
    ESQUEMA_VISTAS,
    NOMBRE_ESTILO,
)

ETIQUETA = "$qml_sig_tec$"


def literal(texto):
    return "'" + texto.replace("'", "''") + "'"


def sql_estilo(capa, qml, base_datos):
    if ETIQUETA in qml:
        raise ValueError(f"{capa.vista}.qml contiene {ETIQUETA}")
    filtro = (
        f"f_table_catalog = {literal(base_datos)} AND f_table_schema = {literal(ESQUEMA_VISTAS)} "
        f"AND f_table_name = {literal(capa.vista)} AND f_geometry_column = {literal(COLUMNA_GEOMETRIA)}"
    )
    descripcion = literal(f"Estilo institucional de {capa.titulo} (qgis/sig_tec/estilos/{capa.vista}.qml)")
    contenido = f"XMLPARSE(DOCUMENT {ETIQUETA}{qml}{ETIQUETA})"
    nombre = literal(NOMBRE_ESTILO)
    return f"""
-- {capa.vista}
UPDATE public.layer_styles SET useasdefault = false
 WHERE {filtro} AND stylename IS DISTINCT FROM {nombre} AND useasdefault IS NOT FALSE;
DELETE FROM public.layer_styles
 WHERE {filtro} AND stylename = {nombre}
   AND id > (SELECT min(id) FROM public.layer_styles WHERE {filtro} AND stylename = {nombre});
UPDATE public.layer_styles
   SET styleqml = {contenido}, useasdefault = true, description = {descripcion}, update_time = now()
 WHERE {filtro} AND stylename = {nombre};
INSERT INTO public.layer_styles
  (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, stylename, styleqml, useasdefault, description)
SELECT {literal(base_datos)}, {literal(ESQUEMA_VISTAS)}, {literal(capa.vista)}, {literal(COLUMNA_GEOMETRIA)},
       {nombre}, {contenido}, true, {descripcion}
 WHERE NOT EXISTS (SELECT FROM public.layer_styles WHERE {filtro} AND stylename = {nombre});
"""


def generar(capas, directorio, base_datos):
    # El bloqueo impide que dos publicaciones simultáneas inserten la misma fila dos veces.
    partes = [
        "SET client_encoding = 'UTF8';",
        "BEGIN;",
        "LOCK TABLE public.layer_styles IN SHARE ROW EXCLUSIVE MODE;",
    ]
    for capa in capas:
        qml = (directorio / f"{capa.vista}.qml").read_text(encoding="utf-8")
        partes.append(sql_estilo(capa, qml, base_datos))
    partes.append("COMMIT;\n")
    return "\n".join(partes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capas", nargs="*", help="vistas a publicar; por omisión, las ocho")
    parser.add_argument("--estilos", type=Path, default=DIRECTORIO_ESTILOS, help="carpeta con los archivos QML")
    parser.add_argument("--base-datos", default=BASE_DATOS, help="valor de f_table_catalog")
    parser.add_argument("--salida", type=Path, help="archivo SQL; por omisión, la salida estándar")
    args = parser.parse_args(argv)

    conocidas = {capa.vista: capa for capa in CAPAS}
    desconocidas = sorted(set(args.capas) - conocidas.keys())
    if desconocidas:
        parser.error("vistas desconocidas: " + ", ".join(desconocidas))
    capas = [conocidas[vista] for vista in args.capas] if args.capas else list(CAPAS)

    sql = generar(capas, args.estilos, args.base_datos)
    if args.salida:
        args.salida.write_text(sql, encoding="utf-8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.write(sql)


if __name__ == "__main__":
    main()
