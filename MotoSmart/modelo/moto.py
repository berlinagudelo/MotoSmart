from db import db
from modelo.clientes import Cliente
from sqlalchemy import Index, text

class Moto(db.Model):
    __tablename__ = 'motos'
    __table_args__ = (
        Index(
            'uq_motos_taller_placa_activa',
            'taller_id',
            'placa',
            unique=True,
            postgresql_where=text('transferida = false'),
            sqlite_where=text('transferida = 0'),
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    placa = db.Column(db.String(20), nullable=False)
    marca = db.Column(db.String(50), nullable=False)
    modelo = db.Column(db.String(50), nullable=False)
    tipo_tecnologia = db.Column(db.String(20), nullable=False, default='electronica')
    transferida = db.Column(db.Boolean, nullable=False, default=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False, index=True)

    # Relación con Cliente
    cliente = db.relationship('Cliente', backref=db.backref('motos', lazy=True))
