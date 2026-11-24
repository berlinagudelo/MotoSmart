"""Registro de auditoría inmutable para operaciones sensibles."""
from datetime import datetime, timezone

from db import db


class Auditoria(db.Model):
    __tablename__ = 'auditoria'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    taller_id = db.Column(
        db.Integer,
        db.ForeignKey('talleres.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey('usuarios.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    entidad = db.Column(db.String(40), nullable=False, index=True)
    entidad_id = db.Column(db.Integer, nullable=True, index=True)
    accion = db.Column(db.String(30), nullable=False, index=True)
    datos_antes = db.Column(db.Text, nullable=True)
    datos_despues = db.Column(db.Text, nullable=True)
    ip = db.Column(db.String(45), nullable=True)
    creada_en = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
