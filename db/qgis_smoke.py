"""Exercise the QGIS PostgreSQL provider against the two editable campus views."""

import os
import sys
import time

from qgis.core import QgsApplication, QgsDataSourceUri, QgsFeature, QgsGeometry, QgsVectorLayer


CAMPUSES = (
    ("Cartago", 1, 55431, "demo_cartago", "SIGTEC_CARTAGO_PASSWORD"),
    ("San Carlos", 3, 55433, "demo_san_carlos", "SIGTEC_SAN_CARLOS_PASSWORD"),
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def open_layer(name, port, user, password):
    uri = QgsDataSourceUri()
    uri.setConnection("127.0.0.1", str(port), "sig_tec", user, password)
    uri.setDataSource("sig", "edificios", "geom", "", "id")
    layer = QgsVectorLayer(uri.uri(False), f"Edificios {name}", "postgres")
    require(layer.isValid(), f"QGIS no pudo cargar la vista de {name}")
    require(layer.fields().indexFromName("id") >= 0, f"Falta id en {name}")
    return layer


def commit(layer, description):
    require(layer.commitChanges(), f"QGIS rechazó {description}: {layer.commitErrors()}")
    layer.reload()


def feature_by_id(layer, feature_id):
    layer.reload()
    return next((feature for feature in layer.getFeatures() if feature["id"] == feature_id), None)


def wait_for(layer, feature_id, expected_name):
    for _ in range(40):
        feature = feature_by_id(layer, feature_id)
        if (feature is None and expected_name is None) or (
            feature is not None and feature["nombre"] == expected_name
        ):
            return
        time.sleep(0.5)
    raise AssertionError(f"QGIS no observó la propagación del edificio {feature_id}")


def exercise(source, peer, campus_id):
    original = next(feature for feature in source.getFeatures() if feature["campus_id"] == campus_id)
    remote = next(feature for feature in source.getFeatures() if feature["campus_id"] != campus_id)
    label = f"Prueba QGIS {campus_id}"

    require(source.startEditing(), f"No se pudo editar el campus {campus_id}")
    new_feature = QgsFeature(source.fields())
    new_feature.setAttribute("nombre", label)
    new_feature.setAttribute("codigo", "QGIS-PRUEBA")
    new_feature.setAttribute("pisos", 1)
    new_feature.setGeometry(original.geometry())
    require(source.addFeature(new_feature), "QGIS rechazó el alta local")
    commit(source, "el alta local")
    inserted = next(feature for feature in source.getFeatures() if feature["nombre"] == label)
    feature_id = inserted["id"]
    require(inserted["campus_id"] == campus_id, "El campus de la fila nueva es incorrecto")
    require((feature_id - campus_id) % 5 == 0, "El ID no sigue la secuencia del campus")
    wait_for(peer, feature_id, label)

    require(source.startEditing(), "No se pudo abrir la edición local")
    updated_geometry = QgsGeometry(inserted.geometry())
    updated_geometry.translate(2, 2)
    require(source.changeGeometry(inserted.id(), updated_geometry), "QGIS rechazó la geometría")
    require(source.changeAttributeValue(inserted.id(), source.fields().indexFromName("nombre"), label + " editado"),
            "QGIS rechazó el atributo")
    commit(source, "la geometría y el nombre")
    wait_for(peer, feature_id, label + " editado")
    peer_geometry = feature_by_id(peer, feature_id).geometry()
    require(peer_geometry.equals(updated_geometry),
            "La geometría editada no llegó al otro campus")

    require(source.startEditing(), "No se pudo abrir la prueba de restricción")
    require(source.changeAttributeValue(remote.id(), source.fields().indexFromName("nombre"), "Cambio ajeno"),
            "QGIS no preparó la edición ajena")
    require(not source.commitChanges(), "QGIS permitió editar un edificio de otro campus")
    source.rollBack()
    require(feature_by_id(source, remote["id"])["nombre"] == remote["nombre"],
            "La edición ajena cambió el dato")

    require(source.startEditing(), "No se pudo abrir el borrado local")
    require(source.deleteFeature(feature_by_id(source, feature_id).id()), "QGIS rechazó el borrado local")
    commit(source, "el borrado local")
    wait_for(peer, feature_id, None)
    print(f"QGIS comprobó alta, edición, geometría, restricción y borrado en el campus {campus_id}")


def main():
    app = QgsApplication([], False)
    app.initQgis()
    try:
        layers = [
            open_layer(name, port, user, os.environ[password_name])
            for name, _, port, user, password_name in CAMPUSES
        ]
        require(all(layer.featureCount() == 2 for layer in layers), "Las vistas deben mostrar dos edificios")
        for source_index, (_, campus_id, _, _, _) in enumerate(CAMPUSES):
            exercise(layers[source_index], layers[1 - source_index], campus_id)
    finally:
        app.exitQgis()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Prueba QGIS fallida: {exc}", file=sys.stderr)
        sys.exit(1)
