from datetime import timedelta
import os
import secrets
import warnings

import click
from flask import render_template
from flask_jwt_extended import JWTManager
from sqlalchemy import inspect, text

from db import db, app
from router.auth import auth_bp
from router.citas import citas_bp
from router.clientes import clientes_bp
from router.motos import motos_bp
from router.scanner import scanner_bp
from router.revision_mecanica import revision_mecanica_bp
from router.inventario import inventario_bp
from router.facturas import facturas_bp
from router.mecanicos import mecanicos_bp
from router.ordenes_servicio import ordenes_bp
from modelo.usuario import Usuario

jwt_secret = os.environ.get('MOTOSMART_JWT_SECRET_KEY', '')
if not jwt_secret:
    jwt_secret = secrets.token_urlsafe(48)
    warnings.warn(
        'MOTOSMART_JWT_SECRET_KEY no está configurada. Se generó una clave temporal; '
        'los tokens dejarán de funcionar al reiniciar MotoSmart.',
        RuntimeWarning,
        stacklevel=1
    )
elif len(jwt_secret) < 32:
    raise RuntimeError('MOTOSMART_JWT_SECRET_KEY debe tener al menos 32 caracteres.')

app.config['JWT_SECRET_KEY'] = jwt_secret
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
app.config['MOTOSMART_PUBLIC_URL'] = os.environ.get(
    'MOTOSMART_PUBLIC_URL', 'http://127.0.0.1:5000'
).rstrip('/')
jwt = JWTManager(app)

@app.route('/')
def home():
    return render_template('index.html')


@app.cli.command('crear-titular-taller')
@click.option('--email', prompt='Correo del titular')
@click.password_option(prompt='Contraseña', confirmation_prompt=True)
def crear_titular_taller(email, password):
    """Crea el titular inicial del taller desde la consola local."""
    db.create_all()
    email = email.strip().lower()
    if not email or '@' not in email or len(email) > 50:
        raise click.ClickException('Ingresa un correo electrónico válido.')
    if Usuario.query.filter_by(rol='mecanico', creado_por_id=None).first():
        raise click.ClickException('Ya existe un titular del taller.')
    if Usuario.query.filter_by(username=email).first():
        raise click.ClickException('Ya existe una cuenta con ese correo.')
    if len(password) < 6:
        raise click.ClickException('La contraseña debe tener al menos 6 caracteres.')

    titular = Usuario(username=email, rol='mecanico')
    titular.set_password(password)
    db.session.add(titular)
    db.session.commit()
    click.echo('Titular del taller creado.')


app.register_blueprint(citas_bp)
app.register_blueprint(motos_bp)
app.register_blueprint(clientes_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(scanner_bp)
app.register_blueprint(revision_mecanica_bp)
app.register_blueprint(inventario_bp)
app.register_blueprint(facturas_bp)
app.register_blueprint(mecanicos_bp)
app.register_blueprint(ordenes_bp)


def inicializar_base():
    db.create_all()
    # db.create_all no agrega columnas a tablas existentes.
    db.session.execute(text("ALTER TABLE motos ADD COLUMN IF NOT EXISTS tipo_tecnologia VARCHAR(20) NOT NULL DEFAULT 'electronica'"))
    db.session.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS creado_por_id INTEGER REFERENCES usuarios(id)"))
    columnas_registro = {
        columna['name']
        for columna in inspect(db.engine).get_columns('registros_pendientes')
    }
    if 'password_hash' not in columnas_registro:
        db.session.execute(text('ALTER TABLE registros_pendientes ADD COLUMN password_hash TEXT'))
    db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        inicializar_base()
    app.run(debug=True)
