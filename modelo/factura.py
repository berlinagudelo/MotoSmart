from datetime import datetime, timezone
from decimal import Decimal

from db import db
from sqlalchemy import CheckConstraint, Index, UniqueConstraint


def _ahora():
    return datetime.now(timezone.utc)


class Factura(db.Model):
    __tablename__ = 'facturas'
    __table_args__ = (
        UniqueConstraint('taller_id', 'numero', name='uq_facturas_taller_numero'),
        UniqueConstraint('taller_id', 'secuencia', name='uq_facturas_taller_secuencia'),
        Index('ix_facturas_taller_fecha', 'taller_id', 'fecha'),
        Index('ix_facturas_taller_estado', 'taller_id', 'estado'),
        UniqueConstraint('taller_id', 'clave_idempotencia', name='uq_facturas_taller_idempotencia'),
        CheckConstraint('subtotal >= 0', name='ck_facturas_subtotal'),
        CheckConstraint('iva >= 0 AND iva <= 100', name='ck_facturas_iva'),
        CheckConstraint('total >= 0', name='ck_facturas_total'),
        CheckConstraint("estado IN ('pendiente', 'pagada', 'anulada')", name='ck_facturas_estado'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    numero = db.Column(db.String(20), nullable=False)
    secuencia = db.Column(db.Integer, nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    descripcion = db.Column(db.String(500), nullable=False)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal('0'))
    iva = db.Column(db.Numeric(5, 2), nullable=False, default=Decimal('19'))
    total = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal('0'))
    estado = db.Column(db.String(15), nullable=False, default='pendiente')
    moto_id = db.Column(
        db.Integer,
        db.ForeignKey('motos.id', ondelete='RESTRICT'),
        nullable=False,
        index=True,
    )
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False)
    clave_idempotencia = db.Column(db.String(64), nullable=True)
    creada_en = db.Column(db.DateTime(timezone=True), nullable=False, default=_ahora)

    moto = db.relationship('Moto', backref=db.backref('facturas', lazy=True))
