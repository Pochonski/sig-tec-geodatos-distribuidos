"""Publica los estilos en el central de un entorno levantado y comprueba la réplica en los campus.

Usa la configuración de entornos.py. Solo necesita Python estándar y la CLI de Docker. Si los
contenedores del entorno no están en ejecución, la prueba se omite.
"""

import sys
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "herramientas"))

import entornos  # noqa: E402
import publicar_estilos  # noqa: E402
from sig_tec.configuracion import CAPAS, DIRECTORIO_ESTILOS, NOMBRE_ESTILO  # noqa: E402

ENTORNO = entornos.actual()
OTRO_ESTILO = "Prueba estilo alternativo"
FILTRO = "f_table_catalog = 'sig_tec' AND f_table_schema = 'sig' AND f_geometry_column = 'geom'"
ESTADO = f"""
SELECT f_table_name,
       count(*) FILTER (WHERE stylename = '{NOMBRE_ESTILO}'),
       count(*) FILTER (WHERE useasdefault),
       coalesce(bool_and(stylename = '{NOMBRE_ESTILO}') FILTER (WHERE useasdefault), false),
       count(*) FILTER (WHERE stylename = '{OTRO_ESTILO}')
  FROM public.layer_styles
 WHERE {FILTRO}
 GROUP BY f_table_name
 ORDER BY f_table_name;
"""


def disponible():
    return all(entornos.contenedor(ENTORNO, servicio) for servicio in ENTORNO.servicios.values())


@unittest.skipUnless(disponible(), f"requiere los contenedores de {ENTORNO.proyecto_compose} en ejecución")
class PruebaPublicacionEnBase(unittest.TestCase):
    def publicar(self):
        entornos.psql(ENTORNO, "central", publicar_estilos.generar(CAPAS, DIRECTORIO_ESTILOS, "sig_tec"))

    def estado(self, servicio):
        filas = entornos.psql(ENTORNO, servicio, ESTADO).splitlines()
        return {fila.split("|")[0]: tuple(fila.split("|")[1:]) for fila in filas}

    def esperar_estado(self, servicio, esperado, segundos=60):
        limite = time.monotonic() + segundos
        actual = self.estado(servicio)
        while actual != esperado and time.monotonic() < limite:
            time.sleep(1)
            actual = self.estado(servicio)
        self.assertEqual(actual, esperado, f"estilos en {servicio}")

    def tearDown(self):
        entornos.psql(ENTORNO, "central", f"DELETE FROM public.layer_styles WHERE {FILTRO} AND stylename = '{OTRO_ESTILO}';")

    def test_una_fila_predeterminada_por_vista_aunque_haya_duplicados(self):
        self.publicar()
        entornos.psql(ENTORNO, "central", f"""
            INSERT INTO public.layer_styles
              (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, stylename, styleqml, useasdefault, description)
            SELECT f_table_catalog, f_table_schema, f_table_name, f_geometry_column, stylename, styleqml, true, 'duplicado de prueba'
              FROM public.layer_styles
             WHERE {FILTRO} AND stylename = '{NOMBRE_ESTILO}' AND f_table_name IN ('edificios', 'iluminacion');
            INSERT INTO public.layer_styles
              (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, stylename, styleqml, useasdefault, description)
            SELECT f_table_catalog, f_table_schema, f_table_name, f_geometry_column, '{OTRO_ESTILO}', styleqml, true, 'estilo de prueba'
              FROM public.layer_styles
             WHERE {FILTRO} AND stylename = '{NOMBRE_ESTILO}' AND f_table_name = 'edificios'
               AND description <> 'duplicado de prueba';
        """)
        antes = self.estado("central")
        self.assertEqual(antes["edificios"], ("2", "3", "f", "1"))
        self.assertEqual(antes["iluminacion"], ("2", "2", "t", "0"))

        self.publicar()

        esperado = {capa.vista: ("1", "1", "t", "0") for capa in CAPAS}
        esperado["edificios"] = ("1", "1", "t", "1")
        for servicio in ENTORNO.servicios.values():
            with self.subTest(servicio=servicio):
                self.esperar_estado(servicio, esperado)


if __name__ == "__main__":
    unittest.main(verbosity=2)
