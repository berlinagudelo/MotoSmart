from db import db


class Cita(db.Model):
    __tablename__ = 'citas'
    __table_args__ = (
        db.UniqueConstraint('moto_id', 'fecha', name='uq_citas_moto_fecha'),
        db.Index('ix_citas_taller_fecha', 'taller_id', 'fecha'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fecha = db.Column(db.Date, nullable=False)
    descripcion = db.Column(db.String(200))
    moto_id = db.Column(
        db.Integer,
        db.ForeignKey('motos.id', ondelete='RESTRICT'),
        nullable=False,
    )
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False)

    moto = db.relationship('Moto', backref='citas')
