"""Extrae una referencia OSM de Cartago. Ejecutar con el Python de QGIS.

Descarga datos vectoriales de un área pequeña, nunca teselas del mapa base.
Los GeoJSON son una referencia de consulta; no escribe en PostgreSQL.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

from qgis.core import QgsApplication, QgsGeometry, QgsVectorLayer

ROOT = Path(__file__).resolve().parents[1]
DESTINO = ROOT / "sig_tec" / "datos" / "cartago"
BBOX = "-83.9143,9.8474,-83.9033,9.8596"
URL = "https://api.openstreetmap.org/api/0.6/map?bbox=" + BBOX
LIMITE = "40819609"


def extraer(archivo, destino=DESTINO):
    raiz = ET.parse(archivo).getroot()
    etiquetas = {
        (elemento.tag, elemento.get("id")): {
            t.get("k"): t.get("v") for t in elemento.findall("tag")
        }
        for elemento in raiz if elemento.tag in ("node", "way", "relation")
    }
    poligonos = QgsVectorLayer(str(archivo) + "|layername=multipolygons", "OSM", "ogr")
    if not poligonos.isValid():
        raise RuntimeError("No se pudo leer el archivo OSM con GDAL/OGR.")
    limites = [f.geometry() for f in poligonos.getFeatures() if str(f["osm_way_id"]) == LIMITE]
    if len(limites) != 1 or not limites[0].isGeosValid():
        raise RuntimeError("Falta el límite válido del campus de Cartago.")
    limite = limites[0]
    capas = {k: [] for k in ("limite", "edificios", "carreteras", "aceras",
                             "parqueos", "zonas_verdes", "puntos_interes",
                             "iluminacion", "accesibilidad")}

    def agregar(capa, geometria, tipo, osm_id, tags):
        if geometria.isEmpty() or not geometria.isGeosValid():
            raise RuntimeError(f"Geometría inválida en {tipo}/{osm_id}.")
        props = {
            "osm_id": f"{tipo}/{osm_id}", "campus_id": 1,
            "nombre": tags.get("name", ""),
            "codigo_osm": tags.get("addr:housenumber", tags.get("ref", "")),
            "tipo": tags.get("amenity", tags.get("highway", tags.get("landuse", tags.get("natural", "")))),
            "fuente": "OpenStreetMap", "url": f"https://www.openstreetmap.org/{tipo}/{osm_id}",
        }
        capas[capa].append({"type": "Feature", "properties": props,
                           "geometry": json.loads(geometria.asJson(7))})

    agregar("limite", limite, "way", LIMITE, etiquetas[("way", LIMITE)])
    for tabla in ("multipolygons", "lines", "points"):
        layer = QgsVectorLayer(str(archivo) + "|layername=" + tabla, tabla, "ogr")
        if not layer.isValid():
            raise RuntimeError("No se pudo abrir " + tabla)
        for f in layer.getFeatures():
            way_id = str(f["osm_way_id"]) if tabla == "multipolygons" else "NULL"
            tipo = "way" if tabla == "lines" or way_id != "NULL" else ("node" if tabla == "points" else "relation")
            osm_id = way_id if way_id != "NULL" else str(f["osm_id"])
            tags = etiquetas.get((tipo, osm_id), {})
            geom = QgsGeometry(f.geometry())
            if not geom.intersects(limite) or osm_id == LIMITE and tipo == "way":
                continue
            if tabla == "multipolygons":
                # No incorporar edificios vecinos cuyo contorno solo roce el campus.
                if not limite.contains(geom.pointOnSurface()):
                    continue
                if tags.get("building") not in (None, "no"):
                    agregar("edificios", geom, tipo, osm_id, tags)
                if tags.get("amenity") == "parking":
                    agregar("parqueos", geom, tipo, osm_id, tags)
                if tags.get("landuse") in ("grass", "forest", "meadow") or tags.get("leisure") in ("garden", "park") or tags.get("natural") in ("wood", "grassland", "scrub"):
                    agregar("zonas_verdes", geom.intersection(limite), tipo, osm_id, tags)
                if tags.get("amenity") in ("library", "restaurant", "cafe", "fast_food", "clinic", "bank", "atm"):
                    agregar("puntos_interes", geom.pointOnSurface(), tipo, osm_id, tags)
            elif tabla == "lines":
                highway = tags.get("highway")
                geom = geom.intersection(limite)
                if geom.isEmpty() or geom.length() == 0:
                    continue
                if highway in ("service", "residential", "unclassified", "tertiary", "living_street"):
                    agregar("carreteras", geom, tipo, osm_id, tags)
                if highway in ("footway", "path", "pedestrian", "steps"):
                    agregar("aceras", geom, tipo, osm_id, tags)
                if highway in ("footway", "path", "pedestrian") and (tags.get("wheelchair") == "yes" or tags.get("ramp") == "yes"):
                    agregar("accesibilidad", geom, tipo, osm_id, tags)
            else:
                if tags.get("highway") == "street_lamp":
                    agregar("iluminacion", geom, tipo, osm_id, tags)
                if tags.get("amenity") in ("library", "restaurant", "cafe", "fast_food", "clinic", "bank", "atm", "drinking_water", "toilets"):
                    agregar("puntos_interes", geom, tipo, osm_id, tags)

    destino.mkdir(parents=True, exist_ok=True)
    conteos, hashes = {}, {}
    for nombre, features in capas.items():
        features.sort(key=lambda f: f["properties"]["osm_id"])
        ruta = destino / (nombre + ".geojson")
        # Un objeto por línea permite revisar cambios de geometría en Git sin
        # sustituir una línea que contenga toda la capa.
        cabecera = json.dumps({"type": "FeatureCollection", "name": nombre}, separators=(",", ":"))[:-1]
        contenido = ",\n".join(json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in features)
        ruta.write_text(cabecera + ',"features":[\n' + contenido + "\n]}\n", encoding="utf-8", newline="\n")
        conteos[nombre] = len(features)
        hashes[ruta.name] = hashlib.sha256(ruta.read_bytes()).hexdigest()
    manifiesto = {
        "fuente": "OpenStreetMap", "url_descarga": URL,
        "fecha_extraccion_utc": datetime.now(timezone.utc).isoformat(),
        "licencia": "ODbL-1.0", "atribucion": "© OpenStreetMap contributors",
        "licencia_url": "https://www.openstreetmap.org/copyright",
        "crs": "EPSG:4326", "limite_osm": "way/" + LIMITE,
        "osm_sha256": hashlib.sha256(Path(archivo).read_bytes()).hexdigest(),
        "conteos": conteos, "sha256": hashes,
        "nota": "Referencia comunitaria sin validación de campo. Sin cobertura no se inventan objetos. Aceras incluye senderos y pasos peatonales OSM.",
    }
    (destino / "fuentes.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return conteos


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm", type=Path, help="Archivo OSM local, sin descargar de nuevo")
    args = parser.parse_args()
    app = QgsApplication([], False)
    app.initQgis()
    with tempfile.TemporaryDirectory(prefix="sigtec-osm-") as temporal:
        try:
            archivo = args.osm or Path(temporal) / "cartago.osm"
            if args.osm is None:
                req = urllib.request.Request(URL, headers={"User-Agent": "SIG-TEC/0.2 (+https://github.com/Pochonski/sig-tec-geodatos-distribuidos)"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    archivo.write_bytes(response.read())
            print(json.dumps(extraer(archivo), ensure_ascii=False))
        finally:
            # OGR mantiene conexiones en un pool: cerrarlo antes de retirar el
            # archivo temporal evita WinError 32 en Windows.
            app.exitQgis()


if __name__ == "__main__":
    main()
