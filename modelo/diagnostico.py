from datetime import datetime, timezone

from db import db


def _ahora():
    return datetime.now(timezone.utc)


class Diagnostico(db.Model):
    __tablename__ = 'diagnosticos'
    __table_args__ = (
        db.Index('ix_diagnosticos_moto_fecha', 'moto_id', 'fecha'),
        db.Index('ix_diagnosticos_taller_fecha', 'taller_id', 'fecha'),
        db.Index(
            'ix_diagnosticos_taller_moto_fecha',
            'taller_id', 'moto_id', 'fecha', 'id',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    moto_id = db.Column(
        db.Integer,
        db.ForeignKey('motos.id', ondelete='RESTRICT'),
        nullable=False,
    )
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False)
    codigo_error = db.Column(db.Text, nullable=False)
    descripcion = db.Column(db.Text)
    detalle_codigos = db.Column(db.Text)
    prioridad = db.Column(db.String(20))
    motivo_prioridad = db.Column(db.Text)
    recomendacion = db.Column(db.Text)
    fecha = db.Column(db.DateTime(timezone=True), nullable=False, default=_ahora)

    moto = db.relationship('Moto', backref='diagnosticos')
