"""Trabajos persistentes de OCR.

La petición HTTP solo valida y encola la imagen. Un worker independiente
(`flask --app app procesar-ocr`) toma el trabajo, ejecuta EasyOCR y guarda el
diagnóstico. Así un reinicio no pierde imágenes pendientes y el servidor web no
queda bloqueado por el OCR.
"""
from datetime import datetime, timezone

from db import db


def _ahora():
    return datetime.now(timezone.utc)


class TrabajoOCR(db.Model):
    __tablename__ = 'trabajos_ocr'
    __table_args__ = (
        db.Index('ix_trabajos_ocr_estado_creado', 'estado', 'creado_en'),
        db.Index('ix_trabajos_ocr_taller_creado', 'taller_id', 'creado_en'),
        db.Index('ix_trabajos_ocr_estado_actualizado', 'estado', 'actualizado_en'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    taller_id = db.Column(
        db.Integer, db.ForeignKey('talleres.id', ondelete='RESTRICT'),
        nullable=False,
    )
    moto_id = db.Column(
        db.Integer, db.ForeignKey('motos.id', ondelete='RESTRICT'),
        nullable=False, index=True,
    )
    usuario_id = db.Column(
        db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )
    estado = db.Column(db.String(20), nullable=False, default='pendiente')
    ruta_archivo = db.Column(db.String(500), nullable=False)
    nombre_original = db.Column(db.String(255), nullable=True)
    tamano = db.Column(db.Integer, nullable=False, default=0)
    intentos = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    max_intentos = db.Column(db.Integer, nullable=False, default=3, server_default='3')
    error = db.Column(db.Text, nullable=True)
    resultado_json = db.Column(db.Text, nullable=True)
    diagnostico_id = db.Column(
        db.Integer, db.ForeignKey('diagnosticos.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )
    creado_en = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_ahora
    )
    actualizado_en = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_ahora, onupdate=_ahora
    )
    iniciado_en = db.Column(db.DateTime(timezone=True), nullable=True)
    terminado_en = db.Column(db.DateTime(timezone=True), nullable=True)

    moto = db.relationship('Moto')
    usuario = db.relationship('Usuario')
