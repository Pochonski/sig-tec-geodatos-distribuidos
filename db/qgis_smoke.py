"""Prueba las ocho vistas editables con el proveedor PostgreSQL de QGIS 3.44 LTR."""

import os
import sys
import time
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsDataSourceUri,
    QgsFeature,
    QgsGeometry,
    QgsVectorLayer,
    QgsWkbTypes,
)


CAMPUSES = (
    ("cartago", 1, 55431, "SIGTEC_CARTAGO_PASSWORD"),
    ("san_jose", 2, 55432, "SIGTEC_SAN_JOSE_PASSWORD"),
    ("san_carlos", 3, 55433, "SIGTEC_SAN_CARLOS_PASSWORD"),
    ("alajuela", 4, 55434, "SIGTEC_ALAJUELA_PASSWORD"),
    ("limon", 5, 55435, "SIGTEC_LIMON_PASSWORD"),
)
LAYERS = {
    "edificios": (QgsWkbTypes.PolygonGeometry, "nombre"),
    "carreteras": (QgsWkbTypes.LineGeometry, "nombre"),
    "aceras": (QgsWkbTypes.LineGeometry, "material"),
    "parqueos": (QgsWkbTypes.PolygonGeometry, "tipo"),
    "zonas_verdes": (QgsWkbTypes.PolygonGeometry, "tipo_vegetacion"),
    "puntos_interes": (QgsWkbTypes.PointGeometry, "nombre"),
    "iluminacion": (QgsWkbTypes.PointGeometry, "codigo"),
    "accesibilidad": (QgsWkbTypes.LineGeometry, "tipo"),
}
CASES = (
    ("cartago", "edificios"),
    ("cartago", "carreteras"),
    ("san_jose", "aceras"),
    ("san_jose", "parqueos"),
    ("san_carlos", "zonas_verdes"),
    ("san_carlos", "puntos_interes"),
    ("alajuela", "iluminacion"),
    ("limon", "accesibilidad"),
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def load_passwords():
    """Carga las contraseñas locales sin mostrarlas en la salida de la prueba."""
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name.startswith("SIGTEC_"):
                os.environ.setdefault(name, value)
    for _, _, _, password_name in CAMPUSES:
        require(os.environ.get(password_name), f"Falta {password_name} en .env")


def open_layer(campus, port, password, layer_name):
    uri = QgsDataSourceUri()
    uri.setConnection("127.0.0.1", str(port), "sig_tec", f"demo_{campus}", password)
    uri.setDataSource("sig", layer_name, "geom", "", "id")
    layer = QgsVectorLayer(uri.uri(False), f"{layer_name} · {campus}", "postgres")
    require(layer.isValid(), f"QGIS no pudo cargar sig.{layer_name} en {campus}")
    require(layer.fields().indexFromName("id") >= 0, f"Falta id en {campus}.{layer_name}")
    require(layer.fields().indexFromName("campus_id") >= 0,
            f"Falta campus_id en {campus}.{layer_name}")
    require(layer.crs().authid() == "EPSG:8908",
            f"CRS incorrecto en {campus}.{layer_name}: {layer.crs().authid()}")
    require(QgsWkbTypes.geometryType(layer.wkbType()) == LAYERS[layer_name][0],
            f"Geometría incorrecta en {campus}.{layer_name}")
    return layer


def features(layer):
    layer.reload()
    return list(layer.getFeatures())


def feature_by_id(layer, feature_id):
    return next((feature for feature in features(layer) if feature["id"] == feature_id), None)


def wait_for(layer, feature_id, predicate, description):
    for _ in range(60):
        feature = feature_by_id(layer, feature_id)
        if predicate(feature):
            return feature
        time.sleep(1)
    raise AssertionError(f"No convergió {description} para id={feature_id} en {layer.name()}")


def commit(layer, description):
    require(layer.commitChanges(), f"QGIS rechazó {description}: {layer.commitErrors()}")
    layer.reload()


def check_inventory(views):
    for campus, _, _, _ in CAMPUSES:
        all_ids = set()
        for layer_name in LAYERS:
            layer = views[campus, layer_name]
            rows = features(layer)
            require(len(rows) == 5, f"{campus}.{layer_name} debe mostrar cinco campus")
            require({row["campus_id"] for row in rows} == {1, 2, 3, 4, 5},
                    f"Falta un campus en {campus}.{layer_name}")
            for row in rows:
                identifier = row["id"]
                require(identifier not in all_ids, f"ID global duplicado en {campus}: {identifier}")
                all_ids.add(identifier)
                require((identifier - row["campus_id"]) % 5 == 0,
                        f"ID fuera de la secuencia en {campus}.{layer_name}")
                require(not row.geometry().isNull() and row.geometry().isGeosValid(),
                        f"Geometría inválida en {campus}.{layer_name}, id={identifier}")
        require(len(all_ids) == 40, f"{campus} debe ver 40 IDs únicos")
    print("QGIS cargó 40 vistas, con 40 IDs únicos, geometrías válidas y EPSG:8908.")


def delete_temporary(layer, feature_id):
    current = feature_by_id(layer, feature_id)
    if current is None:
        return
    if layer.isEditable():
        layer.rollBack()
    require(layer.startEditing(), f"No se pudo iniciar la limpieza de {layer.name()}")
    require(layer.deleteFeature(current.id()), f"No se pudo borrar id={feature_id}")
    commit(layer, f"el borrado temporal en {layer.name()}")


def exercise(source, peers, campus_id, layer_name):
    field_name = LAYERS[layer_name][1]
    existing = features(source)
    own = next(row for row in existing if row["campus_id"] == campus_id)
    remote = next(row for row in existing if row["campus_id"] != campus_id)
    old_ids = {row["id"] for row in existing}
    inserted_id = None

    try:
        require(source.startEditing(), f"No se pudo editar {source.name()}")
        new_feature = QgsFeature(source.fields())
        for field in source.fields():
            if field.name() not in ("id", "campus_id", "geom"):
                new_feature.setAttribute(field.name(), own[field.name()])
        new_geometry = QgsGeometry(own.geometry())
        new_geometry.translate(10, 10)
        new_feature.setGeometry(new_geometry)
        require(source.addFeature(new_feature), f"QGIS rechazó el alta de {layer_name}")
        commit(source, f"el alta en {source.name()}")
        inserted = [row for row in features(source)
                    if row["campus_id"] == campus_id and row["id"] not in old_ids]
        require(len(inserted) == 1, f"No se identificó el nuevo ID de {source.name()}")
        inserted_id = inserted[0]["id"]
        require((inserted_id - campus_id) % 5 == 0,
                f"La secuencia de {source.name()} no asignó el ID esperado")
        for peer in peers:
            wait_for(peer, inserted_id, lambda row: row is not None, "el alta")

        require(source.startEditing(), f"No se pudo editar id={inserted_id}")
        updated_geometry = QgsGeometry(inserted[0].geometry())
        updated_geometry.translate(2, 2)
        updated_value = f"{inserted[0][field_name]} QGIS smoke"
        require(source.changeGeometry(inserted[0].id(), updated_geometry),
                f"QGIS rechazó la geometría de {source.name()}")
        require(source.changeAttributeValue(
            inserted[0].id(), source.fields().indexFromName(field_name), updated_value
        ), f"QGIS rechazó el atributo de {source.name()}")
        commit(source, f"el cambio en {source.name()}")
        for peer in peers:
            wait_for(peer, inserted_id,
                     lambda row: row is not None and row[field_name] == updated_value
                     and row.geometry().equals(updated_geometry), "el atributo y la geometría")

        require(source.startEditing(), f"No se pudo probar el aislamiento en {source.name()}")
        require(source.changeAttributeValue(
            remote.id(), source.fields().indexFromName(field_name), "Cambio ajeno QGIS"
        ), f"QGIS no preparó la edición ajena en {source.name()}")
        require(not source.commitChanges(),
                f"QGIS permitió editar una fila ajena en {source.name()}")
        source.rollBack()
        require(feature_by_id(source, remote["id"])[field_name] == remote[field_name],
                f"Cambió la fila ajena en {source.name()}")

        delete_temporary(source, inserted_id)
        for peer in peers:
            wait_for(peer, inserted_id, lambda row: row is None, "el borrado")
        inserted_id = None
        print(f"QGIS verificó CRUD, geometría y aislamiento: {source.name()}")
    finally:
        if inserted_id is not None:
            delete_temporary(source, inserted_id)


def main():
    load_passwords()
    app = QgsApplication([], False)
    app.initQgis()
    try:
        views = {
            (campus, layer_name): open_layer(campus, port, os.environ[password_name], layer_name)
            for campus, _, port, password_name in CAMPUSES
            for layer_name in LAYERS
        }
        check_inventory(views)
        for campus, layer_name in CASES:
            campus_id = next(identifier for name, identifier, _, _ in CAMPUSES if name == campus)
            peers = [views[name, layer_name] for name, _, _, _ in CAMPUSES if name != campus]
            exercise(views[campus, layer_name], peers, campus_id, layer_name)
        check_inventory(views)
    finally:
        app.exitQgis()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Prueba QGIS fallida: {exc}", file=sys.stderr)
        sys.exit(1)
