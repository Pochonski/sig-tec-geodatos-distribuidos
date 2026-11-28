"""Exporta la referencia vectorial local sin abrir ventanas ni descargar teselas."""
import argparse
import os
from pathlib import Path
import sys

from qgis.core import QgsApplication, QgsMapRendererParallelJob, QgsMapSettings, QgsProject
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase, QPainter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sig_tec import mapas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("salida", type=Path)
    args = parser.parse_args()
    app = QgsApplication([], False)
    app.initQgis()
    # Qt offscreen en Windows puede iniciar sin ninguna fuente. Cargar las
    # fuentes instaladas evita letras vacías y medidas incorrectas de etiquetas.
    if not QFontDatabase().families():
        fuentes = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / n
                   for n in ("segoeui.ttf", "segoeuib.ttf")]
        fuentes += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
        for fuente in fuentes:
            if fuente.is_file():
                QFontDatabase.addApplicationFont(str(fuente))
    if not QFontDatabase().families():
        raise RuntimeError("Qt no encontró fuentes para exportar el mapa.")
    proyecto = QgsProject.instance()
    try:
        grupo = mapas.cargar_referencia(1, proyecto)
        # Excluir deliberadamente la capa XYZ: el servidor público de OSM no
        # se usa para renderizado automático ni descargas anticipadas.
        capas = [n.layer() for n in grupo.findLayers()]
        settings = QgsMapSettings()
        settings.setLayers(capas)
        settings.setDestinationCrs(proyecto.crs())
        settings.setOutputSize(QSize(1600, 1500))
        settings.setOutputDpi(144)
        settings.setBackgroundColor(QColor("#f4f6f4"))
        extension = mapas.extension_sede(1, proyecto)
        extension.scale(1.16)
        settings.setExtent(extension)
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        imagen = job.renderedImage()
        painter = QPainter(imagen)
        painter.fillRect(0, 0, 1600, 95, QColor("#ffffff"))
        painter.fillRect(0, 1390, 1600, 110, QColor("#ffffff"))
        painter.setPen(QColor("#173747"))
        painter.setFont(QFont("Segoe UI", 21, QFont.Weight.Bold))
        painter.drawText(35, 55, "SIG-TEC · Campus Central Cartago")
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(35, 80, "Referencia comunitaria · edificios, vías internas y espacios del campus · EPSG:8908")
        painter.drawText(35, 1425, "© OpenStreetMap contributors · ODbL · https://www.openstreetmap.org/copyright")
        painter.drawText(35, 1453, "Fuente vectorial local: 27 de noviembre de 2026 · Sin validación de campo. No incluye el mapa base en línea.")
        painter.drawText(35, 1480, "Azul: edificios · Gris: vías y parqueos · Ocre: pasos peatonales · Verde: zonas verdes mapeadas")
        painter.end()
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        if not imagen.save(str(args.salida)):
            raise RuntimeError("No se pudo guardar la imagen")
        print(str(args.salida.resolve()))
    finally:
        proyecto.clear()
        app.exitQgis()


if __name__ == "__main__":
    main()
