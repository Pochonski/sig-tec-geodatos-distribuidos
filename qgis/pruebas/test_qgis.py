"""Prueba de integración del complemento con QGIS y el entorno de prueba.

Requiere el Python de QGIS (por ejemplo, la consola OSGeo4W con python-qgis-ltr), el entorno
de qgis/entorno-prueba levantado y los estilos publicados. Sin QGIS, la prueba se omite.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsWkbTypes
except ImportError:
    QgsApplication = None

CLAVE = os.environ.get("CLAVE_PRUEBA", "sigtec-prueba")
PUERTO_BASE = int(os.environ.get("SIG_TEC_PUERTO_BASE", "56430"))


@unittest.skipIf(QgsApplication is None, "requiere el Python de QGIS")
class PruebaComplemento(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Base de autenticación temporal para no tocar el perfil de QGIS.
        cls.directorio = tempfile.TemporaryDirectory()
        os.environ["QGIS_AUTH_DB_DIR_PATH"] = cls.directorio.name
        cls.app = QgsApplication([], False)
        cls.app.initQgis()
        assert QgsApplication.authManager().setMasterPassword("maestra-prueba", True)

        from sig_tec import configuracion, sesion

        cls.configuracion = configuracion
        cls.sesion = sesion
        cls.ajustes = configuracion.Ajustes(puerto_base=PUERTO_BASE)

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().clear()
        cls.app.exitQgis()

    def setUp(self):
        self.proyecto = QgsProject.instance()
        self.proyecto.clear()

    def entrar(self, usuario="cartago_prueba"):
        sesion = self.sesion.iniciar_sesion(self.ajustes, usuario, CLAVE)
        return sesion, self.sesion.cargar_capas(self.ajustes, sesion, self.proyecto)

    def capa(self, carga, vista):
        return next(capa for capa in carga.capas if capa.source().find(f'"{vista}"') >= 0)

    def test_credenciales_invalidas_no_cargan_capas(self):
        with self.assertRaisesRegex(self.configuracion.ErrorSesion, "incorrectos"):
            self.sesion.iniciar_sesion(self.ajustes, "cartago_prueba", "clave-equivocada")
        self.assertEqual(len(self.proyecto.mapLayers()), 0)

    def test_cuenta_sin_campus(self):
        with self.assertRaisesRegex(self.configuracion.ErrorSesion, "no tiene un campus"):
            self.sesion.iniciar_sesion(self.ajustes, "sin_campus_prueba", CLAVE)

    def test_central_no_disponible(self):
        ajustes = self.configuracion.Ajustes(puerto_base=1029)
        with self.assertRaisesRegex(self.configuracion.ErrorSesion, "central no está disponible"):
            self.sesion.iniciar_sesion(ajustes, "cartago_prueba", CLAVE)

    def test_carga_ocho_capas_con_estilo_compartido(self):
        for usuario, campus_id in (("cartago_prueba", 1), ("san_carlos_prueba", 3)):
            with self.subTest(usuario=usuario):
                self.proyecto.clear()
                sesion, carga = self.entrar(usuario)
                self.assertEqual(sesion.campus_id, campus_id)
                self.assertEqual(len(carga.capas), 8)
                for capa, capa_qgis in zip(self.configuracion.CAPAS, carga.capas):
                    self.assertTrue(capa_qgis.isValid(), capa.vista)
                    self.assertEqual(capa_qgis.featureCount(), 5, capa.vista)
                    self.assertEqual(QgsWkbTypes.displayString(capa_qgis.wkbType()), capa.geometria)
                    self.assertEqual(capa_qgis.crs().authid(), "EPSG:8908")
                    self.assertEqual({f["campus_id"] for f in capa_qgis.getFeatures()}, {1, 2, 3, 4, 5})
                self.assertEqual(set(carga.estilos.values()), {self.sesion.ESTILO_BASE_DATOS})
                self.assertEqual(self.capa(carga, "iluminacion").renderer().type(), "categorizedSymbol")

    def test_edicion_local_desde_qgis(self):
        sesion, carga = self.entrar()
        edificios = self.capa(carga, "edificios")
        propio = next(f for f in edificios.getFeatures() if f["campus_id"] == sesion.campus_id)

        nuevo = QgsFeature(edificios.fields())
        nuevo["nombre"] = "Edificio QGIS"
        nuevo["codigo"] = "Q-1"
        nuevo["area"] = 250
        nuevo["pisos"] = 2
        geometria = QgsGeometry(propio.geometry())
        geometria.translate(0, 300)
        nuevo.setGeometry(geometria)
        self.assertTrue(edificios.startEditing())
        self.assertTrue(edificios.addFeature(nuevo))
        self.assertTrue(edificios.commitChanges(), edificios.commitErrors())

        guardado = next(f for f in edificios.getFeatures() if f["nombre"] == "Edificio QGIS")
        self.assertEqual(guardado["campus_id"], sesion.campus_id)
        self.assertEqual((guardado["id"] - sesion.campus_id) % 5, 0)

        self.assertTrue(edificios.startEditing())
        geometria.translate(10, 10)
        edificios.changeGeometry(guardado.id(), geometria)
        edificios.changeAttributeValue(guardado.id(), edificios.fields().indexOf("pisos"), 4)
        self.assertTrue(edificios.commitChanges(), edificios.commitErrors())
        self.assertEqual(edificios.getFeature(guardado.id())["pisos"], 4)

        self.assertTrue(edificios.startEditing())
        self.assertTrue(edificios.deleteFeature(guardado.id()))
        self.assertTrue(edificios.commitChanges(), edificios.commitErrors())
        self.assertFalse(any(f["nombre"] == "Edificio QGIS" for f in edificios.getFeatures()))

    def test_rechaza_editar_objeto_ajeno(self):
        sesion, carga = self.entrar()
        edificios = self.capa(carga, "edificios")
        ajeno = next(f for f in edificios.getFeatures() if f["campus_id"] != sesion.campus_id)

        self.assertTrue(edificios.startEditing())
        edificios.changeAttributeValue(ajeno.id(), edificios.fields().indexOf("nombre"), "Intrusión")
        self.assertFalse(edificios.commitChanges(False))
        self.assertTrue(any("SIG-TEC" in error for error in edificios.commitErrors()), edificios.commitErrors())
        edificios.rollBack()

        self.assertTrue(edificios.startEditing())
        edificios.deleteFeature(ajeno.id())
        self.assertFalse(edificios.commitChanges(False))
        edificios.rollBack()

        edificios.reload()
        self.assertEqual(edificios.getFeature(ajeno.id())["nombre"], ajeno["nombre"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
