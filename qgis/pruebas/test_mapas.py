"""Referencia cartográfica: geometrías, cobertura y carga sin duplicados."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry
    from qgis.PyQt.QtWidgets import QWidget
except ImportError:
    QgsApplication = None


@unittest.skipIf(QgsApplication is None, "requiere el Python de QGIS")
class PruebaMapas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], False)
        cls.app.initQgis()
        from sig_tec import mapas
        cls.mapas = mapas

    def setUp(self):
        QgsProject.instance().clear()
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:8908"))

    def tearDown(self):
        QgsProject.instance().clear()

    def test_geojson_validos_y_trazables(self):
        datos = self.mapas.DATOS / "cartago"
        manifiesto = json.loads((datos / "fuentes.json").read_text(encoding="utf-8"))
        import hashlib
        for nombre, conteo in manifiesto["conteos"].items():
            ruta = datos / (nombre + ".geojson")
            self.assertEqual(hashlib.sha256(ruta.read_bytes()).hexdigest(), manifiesto["sha256"][ruta.name])
            features = json.loads(ruta.read_text(encoding="utf-8"))["features"]
            self.assertEqual(len(features), conteo)
            self.assertEqual(len({f["properties"]["id_referencia"] for f in features}), conteo)
            tipo = "Point" if nombre in ("puntos_interes", "iluminacion") else "LineString" if nombre in ("carreteras", "aceras", "accesibilidad") else "Polygon"
            self.assertTrue(all(f["geometry"]["type"] == tipo for f in features), nombre)
            capa = QgsVectorLayer(str(ruta), nombre, "ogr")
            if features:
                self.assertTrue(capa.isValid())
                self.assertEqual(capa.featureCount(), conteo)
            for f in capa.getFeatures():
                geom = f.geometry()
                self.assertFalse(geom.isEmpty())
                self.assertTrue(geom.isGeosValid(), f["osm_id"])
                self.assertEqual(f["campus_id"], 1)
                self.assertTrue(f["url"].startswith("https://www.openstreetmap.org/"))

    def test_referencia_solo_lectura_sin_duplicados(self):
        proyecto = QgsProject.instance()
        grupo = self.mapas.cargar_referencia(1, proyecto)
        antes = set(proyecto.mapLayers())
        self.assertIs(self.mapas.cargar_referencia(1, proyecto), grupo)
        self.assertEqual(set(proyecto.mapLayers()), antes)
        vectores = [c for c in proyecto.mapLayers().values() if c.customProperty(self.mapas.REFERENCIA)]
        self.assertEqual(len(vectores), 8)
        self.assertTrue(all(c.readOnly() for c in vectores))
        edificios = next(c for c in vectores if c.name() == "Edificios")
        self.assertTrue(any(f["codigo_osm"] == "C3" and "Figueres" in f["nombre"] for f in edificios.getFeatures()))

    def test_cinco_sedes_y_transformacion(self):
        proyecto = QgsProject.instance()
        self.mapas.configurar_transformaciones(proyecto)
        for campus in range(1, 6):
            caja = self.mapas.extension_sede(campus, proyecto)
            self.assertFalse(caja.isEmpty())
            self.assertGreater(caja.xMinimum(), 100000)
            self.assertLess(caja.xMaximum(), 800000)
            self.assertGreater(caja.yMinimum(), 900000)
            self.assertLess(caja.yMaximum(), 1300000)
        self.assertIsNone(self.mapas.cargar_referencia(2, proyecto))
        self.assertEqual(len(proyecto.mapLayers()), 1)

    def test_transformaciones_explicitas_y_eleccion_previa(self):
        proyecto = QgsProject.instance()
        destino = QgsCoordinateReferenceSystem("EPSG:8908")
        origen = QgsCoordinateReferenceSystem("EPSG:4326")
        self.mapas.configurar_transformaciones(proyecto)
        contexto = proyecto.transformContext()
        for codigo in (4326, 3857):
            fuente = QgsCoordinateReferenceSystem(f"EPSG:{codigo}")
            self.assertTrue(contexto.hasTransform(fuente, destino))
            self.assertFalse(contexto.allowFallbackTransform(fuente, destino))
        # Una elección explícita del proyecto tiene prioridad al recargar.
        alternativa = "+proj=pipeline +step +proj=affine +xoff=1"
        self.assertTrue(contexto.addCoordinateOperation(origen, destino, alternativa))
        proyecto.setTransformContext(contexto)
        self.mapas.configurar_transformaciones(proyecto)
        self.assertEqual(proyecto.transformContext().calculateCoordinateOperation(origen, destino), alternativa)

    def test_fondo_oculto_se_vuelve_a_mostrar(self):
        proyecto = QgsProject.instance()
        fondo = self.mapas.asegurar_fondo(proyecto)
        nodo = proyecto.layerTreeRoot().findLayer(fondo.id())
        nodo.setItemVisibilityChecked(False)
        self.assertIs(self.mapas.asegurar_fondo(proyecto), fondo)
        self.assertTrue(nodo.isVisible())
        self.assertEqual(len(proyecto.mapLayers()), 1)

    def test_proyecto_nuevo_conserva_8908_tras_crs_de_primera_capa(self):
        from types import SimpleNamespace
        from sig_tec import complemento
        proyecto = QgsProject.instance()
        proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        canvas = QWidget()
        canvas.setExtent = lambda extension: None
        canvas.refresh = lambda: None
        mensajes = []
        barra = SimpleNamespace(pushInfo=lambda *args: None,
                                pushCritical=lambda *args: mensajes.append(args))
        plugin = complemento.ComplementoSigTec(SimpleNamespace(
            mapCanvas=lambda: canvas, messageBar=lambda: barra))
        original = complemento.cargar_referencia

        def qgis_adopta_crs(*args):
            resultado = original(*args)
            proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
            return resultado

        try:
            with patch("sig_tec.complemento.cargar_referencia", side_effect=qgis_adopta_crs):
                plugin.mostrar_mapa(2)
            self.assertFalse(mensajes)
            self.assertEqual(proyecto.crs().authid(), "EPSG:8908")
        finally:
            plugin.unload()

    def test_alternar_mapa_preserva_ediciones_y_recarga_limpia(self):
        """Ejercita acciones con objetos Qt offscreen; no controla QGIS Desktop."""
        from sig_tec.complemento import ComplementoSigTec
        from sig_tec.sesion import PROPIEDAD_CAMPUS, PROPIEDAD_USUARIO

        class Canvas(QWidget):
            def setExtent(self, extension):
                self.extension = extension

            def refresh(self):
                pass  # No renderizar ni descargar teselas durante las pruebas.

        class Barra:
            def __init__(self):
                self.errores = []

            def pushInfo(self, *args):
                pass

            def pushCritical(self, *args):
                self.errores.append(args)

        class Interfaz:
            def __init__(self):
                self.canvas = Canvas()
                self.ventana = QWidget()
                self.barra = Barra()
                self.acciones = []

            def mainWindow(self):
                return self.ventana

            def mapCanvas(self):
                return self.canvas

            def messageBar(self):
                return self.barra

            def addToolBarIcon(self, accion):
                pass

            def removeToolBarIcon(self, accion):
                pass

            def addPluginToDatabaseMenu(self, menu, accion):
                self.acciones.append(accion)

            def removePluginDatabaseMenu(self, menu, accion):
                self.acciones.remove(accion)

        proyecto = QgsProject.instance()
        capa = QgsVectorLayer("Polygon?crs=EPSG:8908&field=nombre:string", "Edificios de prueba", "memory")
        f = QgsFeature(capa.fields())
        f["nombre"] = "Original"
        f.setGeometry(QgsGeometry.fromWkt("POLYGON((500000 1100000,500010 1100000,500010 1100010,500000 1100000))"))
        capa.dataProvider().addFeatures([f])
        for objeto in (capa,):
            objeto.setCustomProperty(PROPIEDAD_USUARIO, "demo_cartago")
            objeto.setCustomProperty(PROPIEDAD_CAMPUS, 1)
        proyecto.addMapLayer(capa, False)
        grupo = proyecto.layerTreeRoot().addGroup("SIG-TEC · Cartago")
        grupo.setCustomProperty(PROPIEDAD_USUARIO, "demo_cartago")
        grupo.addLayer(capa)
        capa.startEditing()
        fid = next(capa.getFeatures()).id()
        capa.changeAttributeValue(fid, 0, "Pendiente")
        interfaz = Interfaz()
        plugin = ComplementoSigTec(interfaz)
        plugin.initGui()
        try:
            with patch("sig_tec.complemento.QInputDialog.getItem", return_value=("Cartago", True)):
                plugin.ver_mapa()
                inventario = set(proyecto.mapLayers())
                plugin.ver_mapa()
            self.assertFalse(interfaz.barra.errores)
            self.assertEqual(set(proyecto.mapLayers()), inventario)
            self.assertFalse(grupo.isVisible())
            self.assertTrue(capa.isModified())
            self.assertEqual(capa.getFeature(fid)["nombre"], "Pendiente")
            plugin.ver_edicion()
            self.assertTrue(grupo.isVisible())
            self.assertTrue(capa.isEditable() and capa.isModified())
            self.assertFalse(next(g for g in proyecto.layerTreeRoot().findGroups(True)
                                  if g.customProperty(self.mapas.REFERENCIA)).isVisible())
            self.assertIsNotNone(plugin.atribucion)
            plugin.unload()
            plugin.initGui()
            self.assertEqual(len(interfaz.acciones), 4)
            self.assertIsNotNone(plugin.atribucion)
        finally:
            plugin.unload()
            capa.rollBack()


if __name__ == "__main__":
    unittest.main(verbosity=2)
