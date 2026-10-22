from db import db


class ItemInventario(db.Model):
    __tablename__ = 'inventario'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(80), nullable=False)
    categoria = db.Column(db.String(30), nullable=False)
    unidad = db.Column(db.String(20), nullable=False, default='unidades')
    cantidad = db.Column(db.Integer, nullable=False, default=0)
    stock_minimo = db.Column(db.Integer, nullable=False, default=0)
    proveedor = db.Column(db.String(100), nullable=True)
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False, index=True)
