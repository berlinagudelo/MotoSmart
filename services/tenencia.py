from flask import g
from flask_jwt_extended import get_jwt_identity

from db import db
from modelo.usuario import Usuario


def usuario_actual():
    if hasattr(g, 'usuario_actual'):
        return g.usuario_actual
    identidad = get_jwt_identity()
    try:
        usuario = db.session.get(Usuario, int(identidad))
    except (TypeError, ValueError):
        usuario = None
    if usuario is not None and not usuario.activo:
        usuario = None
    g.usuario_actual = usuario
    return usuario


def taller_actual_id():
    usuario = usuario_actual()
    return usuario.taller_id if usuario else None


def es_titular(usuario):
    return bool(
        usuario
        and usuario.rol == 'mecanico'
        and usuario.creado_por_id is None
    )
