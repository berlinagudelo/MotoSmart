from db import db
from modelo.clientes import Cliente

class Moto(db.Model):
    __tablename__ = 'motos'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    placa = db.Column(db.String(20), nullable=False, unique=True)
    marca = db.Column(db.String(50), nullable=False)
    modelo = db.Column(db.String(50), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)

    # Relación con Cliente
    cliente = db.relationship('Cliente', backref=db.backref('motos', lazy=True))
