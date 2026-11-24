from db import db
from werkzeug.security import generate_password_hash, check_password_hash


class Usuario(db.Model):
    __tablename__ = 'usuarios'
    __table_args__ = (
        db.Index('ix_usuarios_taller_rol', 'taller_id', 'rol'),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(254), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    rol = db.Column(db.String(20), nullable=False, default='cliente')
    nombre = db.Column(db.String(100))
    taller_id = db.Column(db.Integer, db.ForeignKey('talleres.id'), nullable=False)
    creado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    token_version = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    email_verificado = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))
    activo = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
