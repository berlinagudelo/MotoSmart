from db import db
from sqlalchemy import UniqueConstraint

class Cliente(db.Model):
    __tablename__ = 'clientes'
    __table_args__ = (UniqueConstraint('taller_id', 'email', name='uq_clientes_taller_email'),)

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20))
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False, index=True)
