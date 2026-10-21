from datetime import datetime

from db import db


class Factura(db.Model):
    __tablename__ = 'facturas'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    numero = db.Column(db.String(20), nullable=False, unique=True)
    fecha = db.Column(db.Date, nullable=False)
    descripcion = db.Column(db.String(500), nullable=False)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    iva = db.Column(db.Numeric(5, 2), nullable=False, default=19)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    estado = db.Column(db.String(15), nullable=False, default='pendiente')
    moto_id = db.Column(db.Integer, db.ForeignKey('motos.id'), nullable=False)
    creada_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    moto = db.relationship('Moto', backref=db.backref('facturas', lazy=True))
