from db import db
from sqlalchemy import Index, UniqueConstraint


class Cliente(db.Model):
    __tablename__ = 'clientes'
    __table_args__ = (
        UniqueConstraint('taller_id', 'email', name='uq_clientes_taller_email'),
        Index('ix_clientes_taller_nombre', 'taller_id', 'nombre'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), nullable=False, index=True)
    telefono = db.Column(db.String(20))
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False)
