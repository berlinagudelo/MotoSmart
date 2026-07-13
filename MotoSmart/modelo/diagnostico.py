from db import db


class Diagnostico(db.Model):
    __tablename__ = 'diagnosticos'

    id = db.Column(db.Integer, primary_key=True)
    moto_id = db.Column(db.Integer, db.ForeignKey('motos.id'))
    codigo_error = db.Column(db.Text, nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    detalle_codigos = db.Column(db.Text, nullable=True)
    prioridad = db.Column(db.String(20), nullable=True)
    motivo_prioridad = db.Column(db.Text, nullable=True)
    recomendacion = db.Column(db.Text, nullable=True)
    fecha = db.Column(db.DateTime, default=db.func.current_timestamp())

    moto = db.relationship('Moto', backref='diagnosticos')
