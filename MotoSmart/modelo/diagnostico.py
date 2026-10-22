from db import db


class Diagnostico(db.Model):
    __tablename__ = 'diagnosticos'

    id = db.Column(db.Integer, primary_key=True)
    moto_id = db.Column(db.Integer, db.ForeignKey('motos.id'))
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False, index=True)
    codigo_error = db.Column(db.Text, nullable=False)
    descripcion = db.Column(db.Text)
    detalle_codigos = db.Column(db.Text)
    prioridad = db.Column(db.String(20))
    motivo_prioridad = db.Column(db.Text)
    recomendacion = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=db.func.current_timestamp())

    moto = db.relationship('Moto', backref='diagnosticos')
