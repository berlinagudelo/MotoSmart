from db import db


class Cita(db.Model):
    __tablename__ = 'citas'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fecha = db.Column(db.Date, nullable=False)
    descripcion = db.Column(db.String(200))
    moto_id = db.Column(db.Integer, db.ForeignKey('motos.id'), nullable=False)
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False, index=True)

    moto = db.relationship('Moto', backref='citas')
