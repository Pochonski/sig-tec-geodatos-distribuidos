"""Pruebas del contrato del complemento que no necesitan QGIS ni la base de datos."""

import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "herramientas"))

import publicar_estilos  # noqa: E402
from sig_tec.configuracion import (  # noqa: E402
    CAPAS,
    CREDENCIALES,
    NO_DISPONIBLE,
    Ajustes,
    clasificar_error_conexion,
)

TIPO_GEOMETRIA_QML = {"Point": "0", "LineString": "1", "Polygon": "2"}


def capas_del_entorno():
    """Lee el diccionario de capas que usa el campus simulado."""
    sql = (RAIZ / "entorno-prueba" / "sql" / "campus.sql").read_text(encoding="utf-8")
    capas = {}
    for vista, geometria, atributos in re.findall(r"\('(\w+)', '(\w+)', '([^']+)', \d\)", sql):
        capas[vista] = (geometria, tuple(columna.split()[0] for columna in re.split(r",\s*(?![^()]*\))", atributos)))
    return capas


class PruebaAjustes(unittest.TestCase):
    def test_puertos_por_campus(self):
        ajustes = Ajustes(puerto_base=56430)
        self.assertEqual(ajustes.puerto_central, 56430)
        self.assertEqual([ajustes.puerto_campus(c) for c in range(1, 6)], [56431, 56432, 56433, 56434, 56435])
        self.assertEqual(Ajustes().puerto_campus(3), 55433)

    def test_campus_desconocido(self):
        with self.assertRaises(ValueError):
            Ajustes().puerto_campus(6)

    def test_clasificacion_de_errores(self):
        self.assertEqual(
            clasificar_error_conexion('FATAL:  password authentication failed for user "cartago_prueba"'), CREDENCIALES
        )
        self.assertEqual(clasificar_error_conexion('FATAL:  role "nadie" does not exist'), CREDENCIALES)
        self.assertEqual(
            clasificar_error_conexion('connection to server at "127.0.0.1", port 56430 failed: Connection refused'),
            NO_DISPONIBLE,
        )
        self.assertEqual(clasificar_error_conexion("timeout expired"), NO_DISPONIBLE)


class PruebaDiccionario(unittest.TestCase):
    def test_capas_coinciden_con_el_entorno(self):
        entorno = capas_del_entorno()
        self.assertEqual(set(entorno), {capa.vista for capa in CAPAS})
        for capa in CAPAS:
            with self.subTest(capa=capa.vista):
                self.assertEqual(entorno[capa.vista], (capa.geometria, capa.atributos))


class PruebaEstilos(unittest.TestCase):
    def test_cada_capa_tiene_un_qml_valido(self):
        for capa in CAPAS:
            with self.subTest(capa=capa.vista):
                raiz = ET.parse(capa.archivo_estilo).getroot()
                self.assertEqual(raiz.tag, "qgis")
                self.assertEqual(raiz.findtext("layerGeometryType"), TIPO_GEOMETRIA_QML[capa.geometria])

                campos = {"id", "campus_id", *capa.atributos}
                referencias = {alias.get("field") for alias in raiz.iter("alias")}
                referencias |= {campo.get("name") for campo in raiz.find("editable")}
                renderer = raiz.find("renderer-v2")
                if renderer.get("attr"):
                    referencias.add(renderer.get("attr"))
                for texto in raiz.iter("text-style"):
                    if texto.get("isExpression") == "1":
                        referencias |= set(re.findall(r'"(\w+)"', texto.get("fieldName")))
                    else:
                        referencias.add(texto.get("fieldName"))
                self.assertLessEqual(referencias, campos)

    def test_id_y_campus_id_no_son_editables(self):
        for capa in CAPAS:
            with self.subTest(capa=capa.vista):
                editable = {c.get("name"): c.get("editable") for c in ET.parse(capa.archivo_estilo).getroot().find("editable")}
                self.assertEqual((editable["id"], editable["campus_id"]), ("0", "0"))

    def test_categorias_de_iluminacion(self):
        raiz = ET.parse(RAIZ / "sig_tec" / "estilos" / "iluminacion.qml").getroot()
        valores = {categoria.get("value") for categoria in raiz.iter("category")}
        self.assertEqual(valores, {"funcional", "mantenimiento", "averiada"})


class PruebaPublicacion(unittest.TestCase):
    def test_sql_publica_las_ocho_capas_en_una_transaccion(self):
        sql = publicar_estilos.generar(CAPAS, RAIZ / "sig_tec" / "estilos", "sig_tec")
        self.assertTrue(sql.startswith("SET client_encoding = 'UTF8';\nBEGIN;"))
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))
        self.assertEqual(sql.count("INSERT INTO public.layer_styles"), 8)
        for capa in CAPAS:
            self.assertIn(f"f_table_name = '{capa.vista}'", sql)

    def test_literales_escapan_comillas(self):
        self.assertEqual(publicar_estilos.literal("O'Higgins"), "'O''Higgins'")

    def test_vista_desconocida(self):
        with self.assertRaises(SystemExit):
            publicar_estilos.main(["calles"])


if __name__ == "__main__":
    unittest.main()
