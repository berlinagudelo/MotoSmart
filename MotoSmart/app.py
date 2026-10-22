from datetime import timedelta
import os
import secrets
import warnings

import click
from flask import render_template
from flask_jwt_extended import JWTManager
from sqlalchemy import inspect

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
    columnas_requeridas = {
        'usuarios': {'taller_id', 'nombre'},
        'clientes': {'taller_id'},
        'motos': {'taller_id', 'transferida'},
        'inventario': {'taller_id'},
        'diagnosticos': {'taller_id'},
        'citas': {'taller_id'},
        'facturas': {'taller_id'},
        'ordenes_servicio': {'taller_id'},
        'registros_pendientes': {'tipo', 'taller_id', 'taller_origen_id'},
    }
    inspector = inspect(db.engine)
    for tabla, requeridas in columnas_requeridas.items():
        existentes = {columna['name'] for columna in inspector.get_columns(tabla)}
        faltantes = requeridas - existentes
        if faltantes:
            raise RuntimeError(
                f'La tabla {tabla} tiene un esquema anterior al sistema de talleres. '
                'Ejecuta el comando de reinicio autorizado: '
                'flask --app app reiniciar-base-talleres --confirmar'
            )
    indices_motos = {
        indice['name'] for indice in inspector.get_indexes('motos')
    }
    if 'uq_motos_taller_placa_activa' not in indices_motos:
        raise RuntimeError(
            'La tabla motos necesita el índice multi-taller actualizado. '
            'Ejecuta el reinicio autorizado: '
            'flask --app app reiniciar-base-talleres --confirmar'
        )


@app.cli.command('reiniciar-base-talleres')
@click.option(
    '--confirmar',
    is_flag=True,
    help='Confirma que se eliminarán todas las tablas y todos sus datos.',
)
def reiniciar_base_talleres(confirmar):
    """Elimina todos los datos y crea el esquema vacío multi-taller."""
    if not confirmar:
        raise click.ClickException(
            'Este comando borra todos los datos. Repite con --confirmar solo para el destino correcto.'
        )
    db.drop_all()
    db.create_all()
    click.echo('Base de datos reiniciada con el esquema multi-taller vacío.')

if __name__ == '__main__':
    with app.app_context():
        inicializar_base()
    app.run(debug=True)
