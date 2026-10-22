from db import db


class Taller(db.Model):
    __tablename__ = 'talleres'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column(db.String(100), nullable=False)
    ciudad = db.Column(db.String(80), nullable=False)
    telefono = db.Column(db.String(20), nullable=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
