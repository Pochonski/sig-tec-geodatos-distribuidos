"""Complemento SIG-TEC para QGIS."""


def classFactory(iface):
    from .complemento import ComplementoSigTec

    return ComplementoSigTec(iface)
