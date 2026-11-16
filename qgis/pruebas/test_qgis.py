"""Prueba de integración del complemento con QGIS 3.44 y una base levantada.

Usa la configuración de entornos.py (SIG_TEC_ENTORNO=simulador o integracion). Requiere el Python
de QGIS, los nodos en ejecución y los estilos publicados. Sin QGIS, la prueba se omite.
"""

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import entornos  # noqa: E402

try:
    from qgis.core import Qgis, QgsApplication, QgsFeature, QgsFeatureRequest, QgsGeometry, QgsProject, QgsWkbTypes
except ImportError:
    QgsApplication = None


@unittest.skipIf(QgsApplication is None, "requiere el Python de QGIS")
class PruebaComplemento(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entorno = entornos.actual()
        # Base de autenticación temporal para no tocar el perfil de QGIS.
        cls.directorio = tempfile.TemporaryDirectory()
        os.environ["QGIS_AUTH_DB_DIR_PATH"] = cls.directorio.name
        cls.app = QgsApplication([], False)
        cls.app.initQgis()
        assert QgsApplication.authManager().setMasterPassword("maestra-prueba", True)

        from sig_tec import configuracion, sesion

        cls.configuracion = configuracion
        cls.sesion = sesion
        cls.ajustes = configuracion.Ajustes(host=entornos.HOST, puerto_base=cls.entorno.puerto_base)
        print(f"\nQGIS {Qgis.version()} contra {cls.entorno.nombre} en {entornos.HOST}:{cls.entorno.puerto_base}")

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().clear()
        cls.app.exitQgis()

    def setUp(self):
        self.proyecto = QgsProject.instance()
        self.proyecto.clear()

    def tearDown(self):
        # Descarta lo que haya quedado en edición antes de limpiar con conexiones nuevas.
        for capa in self.proyecto.mapLayers().values():
            if capa.isEditable():
                capa.rollBack()
        self.proyecto.clear()

    # Utilidades

    def entrar(self, campus_id=1, decidir=None):
        cuenta = self.entorno.cuenta(campus_id)
        sesion = self.sesion.iniciar_sesion(self.ajustes, cuenta.usuario, cuenta.clave)
        return sesion, self.sesion.cargar_capas(self.ajustes, sesion, self.proyecto, decidir)

    def definicion(self, vista):
        return next(capa for capa in self.configuracion.CAPAS if capa.vista == vista)

    def capa(self, carga, vista):
        return carga.capas[self.configuracion.CAPAS.index(self.definicion(vista))]

    def leer(self, sesion, vista, objeto_id):
        """Lee un objeto con una conexión nueva, sin el búfer de edición de las capas del proyecto."""
        capa = self.sesion.crear_capa(self.ajustes, sesion, self.definicion(vista))
        self.assertTrue(capa.isValid())
        return next(capa.getFeatures(QgsFeatureRequest().setFilterExpression(f'"id" = {int(objeto_id)}')), None)

    def borrar_temporales(self, sesion, vista, marcador):
        capa = self.sesion.crear_capa(self.ajustes, sesion, self.definicion(vista))
        temporales = [f.id() for f in capa.getFeatures() if f["nombre"] == marcador]
        if temporales:
            capa.startEditing()
            capa.deleteFeatures(temporales)
            self.assertTrue(capa.commitChanges(), capa.commitErrors())

    def capas_y_grupos(self):
        raiz = self.proyecto.layerTreeRoot()
        return sorted(self.proyecto.mapLayers()), [grupo.name() for grupo in raiz.findGroups(True)]

    def objeto(self, capa, propio, sesion):
        return next(f for f in capa.getFeatures() if (f["campus_id"] == sesion.campus_id) == propio)

    def comprobar_rechazo(self, capa, sesion, vista, objeto, campo):
        """La base rechaza la edición si QGIS no puede confirmarla y la fila sigue igual en la base."""
        self.assertFalse(capa.commitChanges(False), f"QGIS confirmó una edición ajena en {vista}")
        self.assertTrue(capa.commitErrors())
        capa.rollBack()
        guardado = self.leer(sesion, vista, objeto["id"])
        self.assertIsNotNone(guardado)
        self.assertEqual(guardado[campo], objeto[campo])

    # Inicio de sesión

    def test_credenciales_invalidas_no_cargan_capas(self):
        usuario = self.entorno.cuenta(1).usuario
        clave = "clave-equivocada-" + uuid.uuid4().hex
        with self.assertRaisesRegex(self.configuracion.ErrorSesion, "incorrectos") as contexto:
            self.sesion.iniciar_sesion(self.ajustes, usuario, clave)
        self.assertNotIn(clave, str(contexto.exception))
        self.assertEqual(len(self.proyecto.mapLayers()), 0)

    def test_cuenta_sin_campus(self):
        if self.entorno.cuenta_sin_campus is None:
            self.skipTest(f"{self.entorno.nombre} no tiene una cuenta sin campus")
        cuenta = self.entorno.cuenta_sin_campus
        with self.assertRaisesRegex(self.configuracion.ErrorSesion, "no tiene un campus"):
            self.sesion.iniciar_sesion(self.ajustes, cuenta.usuario, cuenta.clave)

    def test_central_no_disponible(self):
        ajustes = self.configuracion.Ajustes(host=entornos.HOST, puerto_base=1029)
        cuenta = self.entorno.cuenta(1)
        with self.assertRaisesRegex(self.configuracion.ErrorSesion, "central no está disponible"):
            self.sesion.iniciar_sesion(ajustes, cuenta.usuario, cuenta.clave)

    def test_carga_ocho_capas_con_estilo_compartido(self):
        for campus_id in (1, 3):
            with self.subTest(campus_id=campus_id):
                sesion, carga = self.entrar(campus_id)
                self.assertEqual(sesion.campus_id, campus_id)
                self.assertEqual(len(self.proyecto.mapLayers()), 8)
                for capa, capa_qgis in zip(self.configuracion.CAPAS, carga.capas):
                    self.assertTrue(capa_qgis.isValid(), capa.vista)
                    self.assertEqual(capa_qgis.featureCount(), 5, capa.vista)
                    self.assertEqual(QgsWkbTypes.displayString(capa_qgis.wkbType()), capa.geometria)
                    self.assertEqual(capa_qgis.crs().authid(), "EPSG:8908")
                    self.assertEqual({f["campus_id"] for f in capa_qgis.getFeatures()}, {1, 2, 3, 4, 5})
                self.assertEqual(set(carga.estilos.values()), {self.sesion.ESTILO_BASE_DATOS})
                self.assertEqual(self.capa(carga, "iluminacion").renderer().type(), "categorizedSymbol")

    # Edición

    def test_edicion_local_desde_qgis(self):
        sesion, carga = self.entrar()
        edificios = self.capa(carga, "edificios")
        propio = self.objeto(edificios, True, sesion)
        marcador = f"QGIS temporal {uuid.uuid4().hex[:8]}"
        # La limpieza corre aunque falle una aserción después del alta.
        self.addCleanup(self.borrar_temporales, sesion, "edificios", marcador)

        nuevo = QgsFeature(edificios.fields())
        nuevo["nombre"] = marcador
        nuevo["codigo"] = "Q-1"
        nuevo["area"] = 250
        nuevo["pisos"] = 2
        geometria = QgsGeometry(propio.geometry())
        geometria.translate(0, 300)
        nuevo.setGeometry(geometria)
        self.assertTrue(edificios.startEditing())
        self.assertTrue(edificios.addFeature(nuevo))
        self.assertTrue(edificios.commitChanges(), edificios.commitErrors())

        guardado = next(f for f in edificios.getFeatures() if f["nombre"] == marcador)
        self.assertEqual(guardado["campus_id"], sesion.campus_id)
        self.assertEqual((guardado["id"] - sesion.campus_id) % 5, 0)

        self.assertTrue(edificios.startEditing())
        geometria.translate(10, 10)
        self.assertTrue(edificios.changeGeometry(guardado.id(), geometria))
        self.assertTrue(edificios.changeAttributeValue(guardado.id(), edificios.fields().indexOf("pisos"), 4))
        self.assertTrue(edificios.commitChanges(), edificios.commitErrors())
        en_base = self.leer(sesion, "edificios", guardado["id"])
        self.assertEqual(en_base["pisos"], 4)
        self.assertTrue(en_base.geometry().equals(geometria))

        self.assertTrue(edificios.startEditing())
        self.assertTrue(edificios.deleteFeature(guardado.id()))
        self.assertTrue(edificios.commitChanges(), edificios.commitErrors())
        self.assertIsNone(self.leer(sesion, "edificios", guardado["id"]))

    def test_rechaza_editar_objeto_ajeno(self):
        sesion, carga = self.entrar()
        edificios = self.capa(carga, "edificios")
        ajeno = self.objeto(edificios, False, sesion)

        self.assertTrue(edificios.startEditing())
        edificios.changeAttributeValue(ajeno.id(), edificios.fields().indexOf("nombre"), "Intrusión")
        self.comprobar_rechazo(edificios, sesion, "edificios", ajeno, "nombre")

        self.assertTrue(edificios.startEditing())
        edificios.deleteFeature(ajeno.id())
        self.comprobar_rechazo(edificios, sesion, "edificios", ajeno, "nombre")

    # Política de sesión

    def test_reinicio_con_edicion_pendiente(self):
        sesion, carga = self.entrar()
        edificios = self.capa(carga, "edificios")
        propio = self.objeto(edificios, True, sesion)
        ajeno = self.objeto(edificios, False, sesion)
        indice = edificios.fields().indexOf("nombre")
        decisiones = []

        def responder(decision):
            def decidir(capas):
                decisiones.append(sorted(capa.name() for capa in capas))
                return decision
            return decidir

        # Cancelar conserva el proyecto, la edición pendiente y la base.
        self.assertTrue(edificios.startEditing())
        edificios.changeAttributeValue(propio.id(), indice, "Edición pendiente")
        antes = self.capas_y_grupos()
        with self.assertRaises(self.sesion.OperacionCancelada):
            self.entrar(decidir=responder(self.sesion.CANCELAR))
        self.assertEqual(decisiones, [["Edificios"]])
        self.assertEqual(self.capas_y_grupos(), antes)
        self.assertTrue(edificios.isEditable() and edificios.isModified())
        self.assertEqual(edificios.getFeature(propio.id())["nombre"], "Edición pendiente")
        self.assertEqual(self.leer(sesion, "edificios", propio["id"])["nombre"], propio["nombre"])
        edificios.rollBack()

        # Sin respuesta se cancela.
        self.assertTrue(edificios.startEditing())
        edificios.changeAttributeValue(propio.id(), indice, "Edición pendiente")
        with self.assertRaises(self.sesion.OperacionCancelada):
            self.entrar()
        self.assertEqual(self.capas_y_grupos(), antes)
        edificios.rollBack()

        # Si guardar falla, no se retira nada y la edición sigue pendiente.
        self.assertTrue(edificios.startEditing())
        edificios.changeAttributeValue(ajeno.id(), indice, "Intrusión")
        with self.assertRaisesRegex(self.configuracion.ErrorSesion, "No se pudieron guardar"):
            self.entrar(decidir=responder(self.sesion.GUARDAR))
        self.assertEqual(self.capas_y_grupos(), antes)
        self.assertTrue(edificios.isEditable() and edificios.isModified())
        self.assertEqual(self.leer(sesion, "edificios", ajeno["id"])["nombre"], ajeno["nombre"])
        edificios.rollBack()

        # Guardar confirma la edición y después reemplaza la sesión.
        marcador = f"QGIS pendiente {uuid.uuid4().hex[:8]}"
        self.addCleanup(self.borrar_temporales, sesion, "edificios", marcador)
        nuevo = QgsFeature(edificios.fields())
        nuevo["nombre"] = marcador
        geometria = QgsGeometry(propio.geometry())
        geometria.translate(0, 400)
        nuevo.setGeometry(geometria)
        self.assertTrue(edificios.startEditing())
        self.assertTrue(edificios.addFeature(nuevo))
        _, nueva = self.entrar(decidir=responder(self.sesion.GUARDAR))
        capas, grupos = self.capas_y_grupos()
        self.assertFalse(set(capas) & set(antes[0]))
        self.assertEqual((len(capas), grupos), (8, [f"SIG-TEC · {sesion.nombre_campus}"]))
        guardado = [f for f in self.capa(nueva, "edificios").getFeatures() if f["nombre"] == marcador]
        self.assertEqual([f["campus_id"] for f in guardado], [sesion.campus_id])

    def test_cambio_de_cartago_a_san_jose(self):
        cartago, carga = self.entrar(1)
        edificios = self.capa(carga, "edificios")
        propio = self.objeto(edificios, True, cartago)
        self.assertTrue(edificios.startEditing())
        edificios.changeAttributeValue(propio.id(), edificios.fields().indexOf("nombre"), "Edición pendiente")
        anteriores = set(self.proyecto.mapLayers())
        decisiones = []

        def descartar(capas):
            decisiones.append(sorted(capa.name() for capa in capas))
            return self.sesion.DESCARTAR

        san_jose, carga = self.entrar(2, decidir=descartar)
        self.assertEqual(decisiones, [["Edificios"]])
        self.assertEqual(san_jose.campus_id, 2)
        self.assertNotEqual(san_jose.authcfg, cartago.authcfg)

        # Solo quedan las capas de la cuenta nueva y ninguna está en edición.
        capas = list(self.proyecto.mapLayers().values())
        self.assertEqual(len(capas), 8)
        self.assertFalse(set(self.proyecto.mapLayers()) & anteriores)
        self.assertEqual(self.capas_y_grupos()[1], ["SIG-TEC · San José"])
        puerto = f"port={self.ajustes.puerto_campus(2)}"
        for capa in capas:
            self.assertEqual(capa.customProperty(self.sesion.PROPIEDAD_USUARIO), self.entorno.cuenta(2).usuario)
            self.assertEqual(int(capa.customProperty(self.sesion.PROPIEDAD_CAMPUS)), 2)
            self.assertFalse(capa.isEditable())
            self.assertIn(puerto, capa.source())
            self.assertIn(f"authcfg={san_jose.authcfg}", capa.source())

        # La edición de Cartago se descartó y la sesión de San José no puede modificar ese objeto.
        self.assertEqual(self.leer(cartago, "edificios", propio["id"])["nombre"], propio["nombre"])
        edificios = self.capa(carga, "edificios")
        de_cartago = next(f for f in edificios.getFeatures() if f["id"] == propio["id"])
        self.assertTrue(edificios.startEditing())
        edificios.changeAttributeValue(de_cartago.id(), edificios.fields().indexOf("nombre"), "Intrusión")
        self.comprobar_rechazo(edificios, san_jose, "edificios", de_cartago, "nombre")


if __name__ == "__main__":
    unittest.main(verbosity=2)
