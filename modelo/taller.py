from datetime import datetime, timezone

from db import db
from sqlalchemy import UniqueConstraint


def _ahora():
    return datetime.now(timezone.utc)


class Taller(db.Model):
    __tablename__ = 'talleres'
    __table_args__ = (
        UniqueConstraint('nombre', 'ciudad', name='uq_talleres_nombre_ciudad'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(100), nullable=False)
    ciudad = db.Column(db.String(80), nullable=False)
    telefono = db.Column(db.String(20), nullable=False)
    creado_en = db.Column(db.DateTime(timezone=True), nullable=False, default=_ahora)
