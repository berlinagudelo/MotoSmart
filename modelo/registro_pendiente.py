from db import db


class RegistroPendiente(db.Model):
    __tablename__ = 'registros_pendientes'
    __table_args__ = (
        db.Index('ix_registros_pendientes_email_tipo', 'email', 'tipo'),
        db.Index('ix_registros_pendientes_expira', 'expires_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False)
    nombre = db.Column(db.String(100))
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.Integer, nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    password_hash = db.Column(db.Text)
    tipo = db.Column(db.String(20), nullable=False, default='registro')
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'))
    taller_origen_id = db.Column(db.Integer, db.ForeignKey('talleres.id'))
    # Datos adicionales serializados en JSON (por ejemplo, los de un taller
    # pendiente de verificación de correo).
    datos = db.Column(db.Text)
