"""Mapas base y referencia OSM de consulta, independientes de las capas editables."""

import json
from pathlib import Path

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDatumTransform, QgsFillSymbol,
    QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsProject,
    QgsRasterLayer, QgsRectangle, QgsTextBufferSettings, QgsTextFormat,
    QgsVectorLayer, QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtWidgets import QLabel

DATOS = Path(__file__).resolve().parent / "datos"
REFERENCIA = "sig_tec/referencia"
FONDO = "sig_tec/fondo"
OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
SEDES = json.loads((DATOS / "sedes.json").read_text(encoding="utf-8"))


class AtribucionMapa(QLabel):
    """Crédito visible en el mapa interactivo; no cambia ajustes globales de QGIS."""
    def __init__(self, canvas):
        super().__init__(canvas)
        self.setText('<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a> · ODbL')
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setOpenExternalLinks(True)
        self.setStyleSheet("QLabel { background: rgba(255,255,255,235); padding: 5px; color: #173747; }")
        self.adjustSize()
        canvas.installEventFilter(self)
        self.ubicar()
        self.show()

    def ubicar(self):
        self.move(max(0, self.parent().width() - self.width() - 10),
                  max(0, self.parent().height() - self.height() - 10))

    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.Type.Resize:
            self.ubicar()
        return False

# Las etiquetas describen lo que OSM permite afirmar; un sendero no se
# presenta como una acera inspeccionada ni como una ruta accesible certificada.
CAPAS_REFERENCIA = (
    ("puntos_interes", "Servicios y puntos de interés", "#d67a17"),
    ("accesibilidad", "Pasos con accesibilidad etiquetada en OSM", "#007b83"),
    ("aceras", "Senderos y pasos peatonales", "#c98e3c"),
    ("carreteras", "Vías internas", "#566675"),
    ("edificios", "Edificios", "#3f6d8c"),
    ("parqueos", "Parqueos", "#9198a5"),
    ("zonas_verdes", "Zonas verdes mapeadas", "#81ac76"),
    ("limite", "Límite del campus según OSM", "#194b65"),
)


def configurar_transformaciones(proyecto):
    """Fija operaciones disponibles de PROJ para Costa Rica solo en este proyecto."""
    destino = QgsCoordinateReferenceSystem("EPSG:8908")
    contexto = proyecto.transformContext()
    for codigo in (4326, 3857):
        origen = QgsCoordinateReferenceSystem(f"EPSG:{codigo}")
        # Respetar la operación elegida previamente por el usuario, incluso
        # si la registró en el sentido inverso.
        if contexto.hasTransform(origen, destino):
            continue
        operaciones = [op for op in QgsDatumTransform.operations(origen, destino)
                       if op.isAvailable and op.proj]
        if not operaciones:
            raise RuntimeError(f"No hay una transformación disponible de EPSG:{codigo} a EPSG:8908.")
        operacion = min(operaciones, key=lambda op: op.accuracy if op.accuracy >= 0 else float("inf"))
        if not contexto.addCoordinateOperation(origen, destino, operacion.proj, allowFallback=False):
            raise RuntimeError(f"No se pudo configurar la transformación desde EPSG:{codigo}.")
    proyecto.setTransformContext(contexto)


def asegurar_fondo(proyecto=None):
    proyecto = proyecto or QgsProject.instance()
    configurar_transformaciones(proyecto)
    if not proyecto.mapLayers() or not proyecto.crs().isValid():
        proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:8908"))
    existentes = [c for c in proyecto.mapLayers().values() if c.customProperty(FONDO)]
    if existentes:
        nodo = proyecto.layerTreeRoot().findLayer(existentes[0].id())
        if nodo is None:
            nodo = proyecto.layerTreeRoot().addLayer(existentes[0])
        nodo.setItemVisibilityChecked(True)
        return existentes[0]
    capa = QgsRasterLayer("type=xyz&url=" + OSM_URL + "&zmin=0&zmax=19",
                          "© OpenStreetMap contributors · mapa base", "wms")
    if not capa.isValid():
        raise RuntimeError("No se pudo crear la conexión al mapa base OpenStreetMap.")
    capa.setCustomProperty(FONDO, True)
    metadata = capa.metadata()
    metadata.setRights(["© OpenStreetMap contributors; ODbL-1.0; https://www.openstreetmap.org/copyright"])
    metadata.setAbstract("Mapa base en línea; requiere Internet. " + OSM_URL)
    capa.setMetadata(metadata)
    proyecto.addMapLayer(capa, False)
    proyecto.layerTreeRoot().addLayer(capa)
    return capa


def estilizar(capa, color, nombre):
    geometria = capa.geometryType()
    if geometria == Qgis.GeometryType.Polygon:
        props = {"color": color, "outline_color": "#294754", "outline_width": "0.2"}
        if nombre == "limite":
            props.update(style="no", outline_color=color, outline_width="0.65", outline_style="dash")
        simbolo = QgsFillSymbol.createSimple(props)
    elif geometria == Qgis.GeometryType.Line:
        simbolo = QgsLineSymbol.createSimple({"line_color": color, "line_width": "0.65" if nombre == "carreteras" else "0.35"})
    else:
        simbolo = QgsMarkerSymbol.createSimple({"name": "circle", "color": color, "size": "2.4", "outline_color": "white"})
    capa.renderer().setSymbol(simbolo)
    if nombre in ("edificios", "puntos_interes"):
        estilo = QgsPalLayerSettings()
        estilo.fieldName = (
            'CASE WHEN coalesce("codigo_osm", \'\') <> \'\' THEN "codigo_osm" ELSE "nombre" END'
            if nombre == "edificios" else
            'CASE WHEN coalesce("nombre", \'\') <> \'\' THEN "nombre" ELSE "codigo_osm" END'
        )
        estilo.isExpression = True
        estilo.autoWrapLength = 25
        formato = QgsTextFormat()
        formato.setFont(QFont("Segoe UI", 9))
        formato.setSize(9)
        formato.setColor(QColor("#173747"))
        halo = QgsTextBufferSettings()
        halo.setEnabled(True)
        halo.setSize(0.8)
        halo.setColor(QColor("white"))
        formato.setBuffer(halo)
        estilo.setFormat(formato)
        capa.setLabeling(QgsVectorLayerSimpleLabeling(estilo))
        capa.setLabelsEnabled(True)


def cargar_referencia(campus_id, proyecto=None):
    """Carga datos locales de Cartago una sola vez; no requiere login ni escribe en la BD."""
    proyecto = proyecto or QgsProject.instance()
    clave = str(campus_id)
    if clave not in SEDES:
        raise ValueError("Campus desconocido")
    asegurar_fondo(proyecto)
    if campus_id != 1:
        return None
    existente = next((g for g in proyecto.layerTreeRoot().findGroups(True)
                      if g.customProperty(REFERENCIA) == "cartago"), None)
    if existente:
        existente.setItemVisibilityChecked(True)
        return existente
    pares = []
    for archivo, titulo, color in CAPAS_REFERENCIA:
        ruta = DATOS / "cartago" / (archivo + ".geojson")
        capa = QgsVectorLayer(str(ruta), titulo, "ogr")
        if not capa.isValid():
            raise RuntimeError("No se pudo abrir la referencia " + archivo)
        if not capa.featureCount():
            continue
        capa.setReadOnly(True)
        capa.setCustomProperty(REFERENCIA, "cartago")
        metadata = capa.metadata()
        metadata.setRights(["© OpenStreetMap contributors; ODbL-1.0"])
        metadata.setAbstract("Referencia comunitaria de consulta, sin validación de campo. Ver datos/cartago/fuentes.json.")
        capa.setMetadata(metadata)
        estilizar(capa, color, archivo)
        pares.append(capa)
    grupo = proyecto.layerTreeRoot().insertGroup(0, "Cartago · referencia OpenStreetMap")
    grupo.setCustomProperty(REFERENCIA, "cartago")
    for capa in pares:
        proyecto.addMapLayer(capa, False)
        grupo.addLayer(capa)
    return grupo


def extension_sede(campus_id, proyecto=None):
    proyecto = proyecto or QgsProject.instance()
    origen = QgsCoordinateReferenceSystem("EPSG:4326")
    destino = proyecto.crs()
    return QgsCoordinateTransform(origen, destino, proyecto).transformBoundingBox(
        QgsRectangle(*SEDES[str(campus_id)]["bbox"]))
