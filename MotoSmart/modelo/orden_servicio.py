from datetime import datetime

from db import db
from sqlalchemy import UniqueConstraint


class OrdenServicio(db.Model):
    __tablename__ = 'ordenes_servicio'
    __table_args__ = (UniqueConstraint('taller_id', 'numero', name='uq_ordenes_taller_numero'),)

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    numero = db.Column(db.String(20), nullable=False)
    moto_id = db.Column(db.Integer, db.ForeignKey('motos.id'), nullable=False)
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False, index=True)
    descripcion = db.Column(db.String(800), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='recibida')
    creada_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    actualizada_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    moto = db.relationship('Moto', backref=db.backref('ordenes_servicio', lazy=True))
    repuestos = db.relationship('OrdenRepuesto', backref='orden', lazy=True, cascade='all, delete-orphan')


class OrdenRepuesto(db.Model):
    __tablename__ = 'ordenes_repuestos'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('ordenes_servicio.id'), nullable=False)
    inventario_id = db.Column(db.Integer, db.ForeignKey('inventario.id'), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)

    item = db.relationship('ItemInventario')
