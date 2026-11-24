from datetime import datetime, timezone

from db import db
from sqlalchemy import CheckConstraint, Index, UniqueConstraint


def _ahora():
    return datetime.now(timezone.utc)


class OrdenServicio(db.Model):
    __tablename__ = 'ordenes_servicio'
    __table_args__ = (
        UniqueConstraint('taller_id', 'numero', name='uq_ordenes_taller_numero'),
        UniqueConstraint('taller_id', 'secuencia', name='uq_ordenes_taller_secuencia'),
        UniqueConstraint('taller_id', 'clave_idempotencia', name='uq_ordenes_taller_idempotencia'),
        Index('ix_ordenes_taller_estado', 'taller_id', 'estado'),
        Index('ix_ordenes_taller_creada', 'taller_id', 'creada_en'),
        Index('ix_ordenes_taller_actualizada', 'taller_id', 'actualizada_en'),
        CheckConstraint(
            "estado IN ('recibida', 'diagnostico', 'reparacion', 'lista', 'entregada', 'cancelada')",
            name='ck_ordenes_estado',
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    numero = db.Column(db.String(20), nullable=False)
    secuencia = db.Column(db.Integer, nullable=False)
    moto_id = db.Column(
        db.Integer,
        db.ForeignKey('motos.id', ondelete='RESTRICT'),
        nullable=False,
        index=True,
    )
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False)
    descripcion = db.Column(db.String(800), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='recibida')
    clave_idempotencia = db.Column(db.String(64), nullable=True)
    creada_en = db.Column(db.DateTime(timezone=True), nullable=False, default=_ahora)
    actualizada_en = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_ahora, onupdate=_ahora
    )

    moto = db.relationship('Moto', backref=db.backref('ordenes_servicio', lazy=True))
    repuestos = db.relationship(
        'OrdenRepuesto', backref='orden', lazy=True, cascade='all, delete-orphan'
    )


class OrdenRepuesto(db.Model):
    __tablename__ = 'ordenes_repuestos'
    __table_args__ = (
        UniqueConstraint('orden_id', 'inventario_id', name='uq_orden_repuesto_item'),
        CheckConstraint('cantidad >= 1', name='ck_orden_repuesto_cantidad'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    orden_id = db.Column(
        db.Integer,
        db.ForeignKey('ordenes_servicio.id', ondelete='CASCADE'),
        nullable=False,
    )
    inventario_id = db.Column(
        db.Integer,
        db.ForeignKey('inventario.id', ondelete='RESTRICT'),
        nullable=False,
        index=True,
    )
    cantidad = db.Column(db.Integer, nullable=False)

    item = db.relationship('ItemInventario')
