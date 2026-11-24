import logging
import os
import secrets
import warnings
from datetime import timedelta

import click
from flask import jsonify, render_template, request
from flask_jwt_extended import JWTManager
from flask_jwt_extended.exceptions import CSRFError as JWT_CSRFError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from db import db, app
from modelo.taller import Taller
from modelo.usuario import Usuario
from services.ocr_queue import (
    ejecutar_worker,
    iniciar_trabajador_en_hilo,
    limpiar_trabajos,
)
from services.privacidad import (
    ErrorPrivacidad,
    anonimizar_usuario,
    aplicar_retencion,
    exportar_json,
)
from services.seguridad import estado_almacen_limites, limitar, registrar_auditoria
from services.validacion import ErrorValidacion, email_valor, password as validar_password
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


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('motorsmart')

ENTORNO = os.environ.get('MOTOSMART_ENV', 'development').strip().lower()
ES_PRODUCCION = ENTORNO in ('production', 'prod')
APP_VERSION = '1.0.0'

# ---------------------------------------------------------------------------
# Configuración de seguridad
# ---------------------------------------------------------------------------
jwt_secret = os.environ.get('MOTOSMART_JWT_SECRET_KEY', '')
if not jwt_secret:
    if ES_PRODUCCION:
        raise RuntimeError(
            'MOTOSMART_JWT_SECRET_KEY es obligatoria en producción. '
            'Configura una clave persistente de al menos 32 caracteres.'
        )
    jwt_secret = secrets.token_urlsafe(48)
    warnings.warn(
        'MOTOSMART_JWT_SECRET_KEY no está configurada. Se generó una clave temporal; '
        'los tokens dejarán de funcionar al reiniciar MotoSmart.',
        RuntimeWarning,
        stacklevel=1,
    )
elif len(jwt_secret) < 32:
    raise RuntimeError('MOTOSMART_JWT_SECRET_KEY debe tener al menos 32 caracteres.')

try:
    jwt_minutos = int(os.environ.get('MOTOSMART_JWT_MINUTOS', '60'))
except ValueError:
    jwt_minutos = 60
jwt_minutos = max(5, min(jwt_minutos, 24 * 60))

app.config['JWT_SECRET_KEY'] = jwt_secret
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=jwt_minutos)
# La sesión del navegador viaja en una cookie HttpOnly. Se mantiene la cabecera
# Bearer para integraciones y pruebas automatizadas, pero el frontend ya no
# guarda ni envía el token en JavaScript.
app.config['JWT_TOKEN_LOCATION'] = ['headers', 'cookies']
app.config['JWT_HEADER_TYPE'] = 'Bearer'
app.config['JWT_COOKIE_SECURE'] = ES_PRODUCCION
app.config['JWT_COOKIE_SAMESITE'] = 'Strict'
app.config['JWT_COOKIE_CSRF_PROTECT'] = True
app.config['JWT_CSRF_IN_COOKIES'] = True
app.config['JWT_ACCESS_COOKIE_PATH'] = '/'
app.config['JWT_REFRESH_COOKIE_PATH'] = '/'
app.config['JWT_SESSION_COOKIE'] = True
_cookie_domain = os.environ.get('MOTOSMART_COOKIE_DOMAIN', '').strip() or None
if _cookie_domain:
    app.config['JWT_COOKIE_DOMAIN'] = _cookie_domain
app.config['MOTOSMART_RETURN_TOKEN_IN_BODY'] = (
    os.environ.get(
        'MOTOSMART_RETURN_TOKEN_IN_BODY', 'false' if ES_PRODUCCION else 'true'
    ).strip().lower() in ('1', 'true', 'yes')
)

public_url = os.environ.get('MOTOSMART_PUBLIC_URL', 'http://127.0.0.1:5000').rstrip('/')
if ES_PRODUCCION and not public_url.startswith('https://'):
    raise RuntimeError('MOTOSMART_PUBLIC_URL debe usar HTTPS en producción.')
app.config['MOTOSMART_PUBLIC_URL'] = public_url
app.config['MOTOSMART_ENV'] = ENTORNO
app.config['MOTOSMART_REQUIRE_EMAIL_VERIFICATION'] = (
    os.environ.get('MOTOSMART_REQUIRE_EMAIL_VERIFICATION', 'true' if ES_PRODUCCION else 'false')
    .strip().lower() in ('1', 'true', 'yes', 'si', 'sí')
)

try:
    max_upload_mb = int(os.environ.get('MOTOSMART_MAX_UPLOAD_MB', '10'))
except ValueError:
    max_upload_mb = 10
max_upload_mb = max(1, min(max_upload_mb, 50))
app.config['MAX_CONTENT_LENGTH'] = max_upload_mb * 1024 * 1024
app.config['MOTOSMART_MAX_UPLOAD_MB'] = max_upload_mb
app.config['RATELIMIT_ENABLED'] = (
    os.environ.get('MOTOSMART_RATELIMIT', 'true').strip().lower()
    not in ('0', 'false', 'no')
)
# Almacén compartido para límites entre múltiples workers/instancias. Sin Redis
# la aplicación mantiene el contador en memoria y lo advierte en /health.
app.config['MOTOSMART_REDIS_URL'] = os.environ.get('MOTOSMART_REDIS_URL', '').strip() or None

# Cola persistente de OCR. En desarrollo/escritorio se puede activar un hilo
# interno; en producción se ejecuta un proceso aparte con el comando
# `flask --app app procesar-ocr`.
app.config['MOTOSMART_OCR_DIR'] = (
    os.environ.get('MOTOSMART_OCR_DIR', '').strip()
    or os.path.join(app.instance_path, 'ocr')
)
app.config['MOTOSMART_OCR_INLINE_WORKER'] = (
    os.environ.get(
        'MOTOSMART_OCR_INLINE_WORKER', 'true' if not ES_PRODUCCION else 'false'
    ).strip().lower() in ('1', 'true', 'yes')
)
try:
    app.config['MOTOSMART_OCR_MAX_INTENTOS'] = max(
        1, min(int(os.environ.get('MOTOSMART_OCR_MAX_INTENTOS', '3')), 10)
    )
except ValueError:
    app.config['MOTOSMART_OCR_MAX_INTENTOS'] = 3
try:
    app.config['MOTOSMART_OCR_TIMEOUT_SEGUNDOS'] = max(
        30, int(os.environ.get('MOTOSMART_OCR_TIMEOUT_SEGUNDOS', '600'))
    )
except ValueError:
    app.config['MOTOSMART_OCR_TIMEOUT_SEGUNDOS'] = 600
try:
    app.config['MOTOSMART_RETENCION_AUDITORIA_DIAS'] = max(
        30, int(os.environ.get('MOTOSMART_RETENCION_AUDITORIA_DIAS', '730'))
    )
except ValueError:
    app.config['MOTOSMART_RETENCION_AUDITORIA_DIAS'] = 730
try:
    app.config['MOTOSMART_RETENCION_OCR_DIAS'] = max(
        1, int(os.environ.get('MOTOSMART_RETENCION_OCR_DIAS', '90'))
    )
except ValueError:
    app.config['MOTOSMART_RETENCION_OCR_DIAS'] = 90
try:
    app.config['MOTOSMART_RETENCION_CUENTAS_DIAS'] = max(
        30, int(os.environ.get('MOTOSMART_RETENCION_CUENTAS_DIAS', '365'))
    )
except ValueError:
    app.config['MOTOSMART_RETENCION_CUENTAS_DIAS'] = 365
try:
    app.config['MOTOSMART_RETENCION_LOTE'] = max(
        100, int(os.environ.get('MOTOSMART_RETENCION_LOTE', '5000'))
    )
except ValueError:
    app.config['MOTOSMART_RETENCION_LOTE'] = 5000
app.config['MOTOSMART_AUTO_MIGRATE'] = (
    os.environ.get(
        'MOTOSMART_AUTO_MIGRATE', 'false' if ES_PRODUCCION else 'true'
    ).strip().lower() in ('1', 'true', 'yes')
)
app.config['PROPAGATE_EXCEPTIONS'] = False
app.config['JSON_SORT_KEYS'] = False

if os.environ.get('MOTOSMART_TRUST_PROXY', '').strip().lower() in ('1', 'true', 'yes'):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

jwt = JWTManager(app)


@jwt.token_in_blocklist_loader
def token_revocado(jwt_header, jwt_payload):
    """Invalida tokens de cuentas eliminadas, desactivadas o con versión antigua."""
    identidad = jwt_payload.get('sub')
    try:
        usuario_id = int(identidad)
    except (TypeError, ValueError):
        return True
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None or not usuario.activo:
        return True
    return int(jwt_payload.get('tv', -1)) != int(usuario.token_version or 0)


@jwt.unauthorized_loader
def falta_token(motivo):
    return jsonify({'error': 'Debes iniciar sesión para realizar esta acción.'}), 401


@jwt.invalid_token_loader
def token_invalido(motivo):
    return jsonify({'error': 'El token de acceso no es válido.'}), 401


@jwt.expired_token_loader
def token_vencido(jwt_header, jwt_payload):
    return jsonify({'error': 'La sesión venció. Inicia sesión de nuevo.'}), 401


@jwt.revoked_token_loader
def token_revocado_respuesta(jwt_header, jwt_payload):
    return jsonify({'error': 'La sesión fue revocada. Inicia sesión de nuevo.'}), 401


@app.errorhandler(JWT_CSRFError)
def csrf_invalido(error):
    return jsonify({
        'error': 'La solicitud no tiene un token CSRF válido. Recarga la página e inténtalo de nuevo.'
    }), 401


# ---------------------------------------------------------------------------
# Manejo global de errores: todas las respuestas de API son JSON
# ---------------------------------------------------------------------------
MENSAJES_HTTP = {
    400: 'Solicitud inválida.',
    401: 'No autenticado.',
    403: 'No tienes permisos para esta acción.',
    404: 'Recurso no encontrado.',
    405: 'Método no permitido.',
    409: 'La operación entra en conflicto con datos existentes.',
    413: 'El archivo supera el tamaño máximo permitido.',
    415: 'Tipo de contenido no soportado. Envía JSON.',
    422: 'Los datos no se pudieron procesar.',
    429: 'Demasiadas solicitudes.',
}


@app.errorhandler(ErrorValidacion)
def manejar_validacion(error):
    db.session.rollback()
    return jsonify({'error': error.mensaje}), error.status


@app.errorhandler(IntegrityError)
def manejar_integridad(error):
    db.session.rollback()
    logger.warning('Conflicto de integridad: %s', error)
    return jsonify({
        'error': 'La operación entra en conflicto con datos existentes. '
                 'Revisa duplicados o registros relacionados.'
    }), 409


@app.errorhandler(OperationalError)
def manejar_operacional(error):
    db.session.rollback()
    logger.exception('Error operacional de base de datos.')
    return jsonify({
        'error': 'La base de datos no está disponible en este momento. Inténtalo más tarde.'
    }), 503


@app.errorhandler(HTTPException)
def manejar_http(error):
    mensaje = MENSAJES_HTTP.get(error.code, error.description)
    if error.code == 405 and getattr(error, 'valid_methods', None):
        respuesta = jsonify({'error': mensaje, 'metodos_permitidos': sorted(error.valid_methods)})
    else:
        respuesta = jsonify({'error': mensaje})
    respuesta.status_code = error.code
    return respuesta


@app.errorhandler(Exception)
def manejar_error(error):
    db.session.rollback()
    logger.exception('Error no controlado en %s %s', request.method, request.path)
    return jsonify({
        'error': 'Ocurrió un error interno. El equipo técnico fue notificado.'
    }), 500


@app.after_request
def cabeceras_seguridad(respuesta):
    respuesta.headers.setdefault('X-Content-Type-Options', 'nosniff')
    respuesta.headers.setdefault('X-Frame-Options', 'DENY')
    respuesta.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    respuesta.headers.setdefault('X-MotoSmart-Version', APP_VERSION)
    respuesta.headers.setdefault(
        'Permissions-Policy', 'geolocation=(), microphone=(), camera=()'
    )
    respuesta.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    if request.is_secure or ES_PRODUCCION:
        respuesta.headers.setdefault(
            'Strict-Transport-Security', 'max-age=31536000; includeSubDomains'
        )
    if respuesta.mimetype == 'application/json':
        respuesta.headers.setdefault('Cache-Control', 'no-store')
    return respuesta


# ---------------------------------------------------------------------------
# Rutas base
# ---------------------------------------------------------------------------
@app.route('/')
def home():
    return render_template('index.html')


@app.route('/health', methods=['GET'])
@limitar(120, 60, nombre='health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({
            'status': 'ok',
            'database': 'ok',
            'version': APP_VERSION,
            'rate_limit': estado_almacen_limites(),
        }), 200
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception('Healthcheck de base de datos falló.')
        return jsonify({
            'status': 'error',
            'database': 'unavailable',
            'version': APP_VERSION,
            'rate_limit': estado_almacen_limites(),
        }), 503


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


# ---------------------------------------------------------------------------
# Esquema y migraciones ligeras
# ---------------------------------------------------------------------------
def _columnas(tabla):
    return {columna['name'] for columna in inspect(db.engine).get_columns(tabla)}


def _agregar_columna(tabla, columna, tipo_sql, default_sql=None):
    if columna in _columnas(tabla):
        return False
    sentencia = f'ALTER TABLE {tabla} ADD COLUMN {columna} {tipo_sql}'
    if default_sql is not None:
        sentencia += f' DEFAULT {default_sql}'
    db.session.execute(text(sentencia))
    db.session.commit()
    return True


def _crear_indice(nombre, tabla, columnas, unico=False):
    prefijo = 'CREATE UNIQUE INDEX' if unico else 'CREATE INDEX'
    sentencia = f'{prefijo} IF NOT EXISTS {nombre} ON {tabla} ({columnas})'
    try:
        db.session.execute(text(sentencia))
        db.session.commit()
    except (IntegrityError, OperationalError, SQLAlchemyError) as error:
        db.session.rollback()
        logger.warning('No se pudo crear el índice %s: %s', nombre, error)


def _migrar_esquema():
    """Migraciones idempotentes para instalaciones anteriores.

    No sustituye a Alembic, pero evita que una base existente quede inservible
    al actualizar el código. En producción se recomienda versionar el esquema.
    """
    _agregar_columna('usuarios', 'token_version', 'INTEGER NOT NULL', '0')
    _agregar_columna('usuarios', 'email_verificado', 'BOOLEAN NOT NULL', 'TRUE')
    _agregar_columna('usuarios', 'activo', 'BOOLEAN NOT NULL', 'TRUE')
    _agregar_columna('facturas', 'secuencia', 'INTEGER')
    _agregar_columna('facturas', 'clave_idempotencia', 'VARCHAR(64)')
    _agregar_columna('ordenes_servicio', 'secuencia', 'INTEGER')
    _agregar_columna('ordenes_servicio', 'clave_idempotencia', 'VARCHAR(64)')

    if db.engine.dialect.name == 'postgresql':
        for tabla, columna in (
            ('usuarios', 'username'),
            ('clientes', 'email'),
            ('registros_pendientes', 'email'),
        ):
            try:
                db.session.execute(text(
                    f'ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE VARCHAR(254)'
                ))
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()

    # Rellenar secuencias por taller sin dejar huecos.
    for tabla, prefijo in (
        ('facturas', 'FAC'),
        ('ordenes_servicio', 'OS'),
    ):
        columnas = _columnas(tabla)
        if 'secuencia' not in columnas:
            continue
        maximos = dict(db.session.execute(text(
            f'SELECT taller_id, COALESCE(MAX(secuencia), 0) FROM {tabla} GROUP BY taller_id'
        )).all())
        pendientes = db.session.execute(text(
            f'SELECT id, taller_id FROM {tabla} WHERE secuencia IS NULL ORDER BY taller_id, id'
        )).all()
        for fila_id, taller_id in pendientes:
            maximos[taller_id] = maximos.get(taller_id, 0) + 1
            db.session.execute(
                text(f'UPDATE {tabla} SET secuencia = :secuencia WHERE id = :id'),
                {'secuencia': maximos[taller_id], 'id': fila_id},
            )
        db.session.execute(text(
            f"UPDATE {tabla} SET numero = '{prefijo}-' || printf('%06d', secuencia) "
            f"WHERE numero = 'PENDIENTE' AND secuencia IS NOT NULL"
            if db.engine.dialect.name == 'sqlite' else
            f"UPDATE {tabla} SET numero = '{prefijo}-' || LPAD(secuencia::text, 6, '0') "
            f"WHERE numero = 'PENDIENTE' AND secuencia IS NOT NULL"
        ))
        db.session.commit()

    indices = [
        ('ix_motos_cliente_id', 'motos', 'cliente_id', False),
        ('ix_motos_taller_cliente', 'motos', 'taller_id, cliente_id', False),
        ('ix_citas_moto_id', 'citas', 'moto_id', False),
        ('ix_citas_taller_fecha', 'citas', 'taller_id, fecha', False),
        ('ix_diagnosticos_moto_id', 'diagnosticos', 'moto_id', False),
        ('ix_diagnosticos_moto_fecha', 'diagnosticos', 'moto_id, fecha', False),
        ('ix_facturas_moto_id', 'facturas', 'moto_id', False),
        ('ix_facturas_taller_fecha', 'facturas', 'taller_id, fecha', False),
        ('ix_facturas_taller_estado', 'facturas', 'taller_id, estado', False),
        ('ix_facturas_taller_secuencia', 'facturas', 'taller_id, secuencia', True),
        ('ix_ordenes_moto_id', 'ordenes_servicio', 'moto_id', False),
        ('ix_ordenes_taller_estado', 'ordenes_servicio', 'taller_id, estado', False),
        ('ix_ordenes_taller_creada', 'ordenes_servicio', 'taller_id, creada_en', False),
        ('ix_ordenes_taller_secuencia', 'ordenes_servicio', 'taller_id, secuencia', True),
        ('ix_ordenes_repuestos_orden_id', 'ordenes_repuestos', 'orden_id', False),
        ('ix_ordenes_repuestos_inventario_id', 'ordenes_repuestos', 'inventario_id', False),
        ('ix_inventario_taller_nombre', 'inventario', 'taller_id, nombre', True),
        ('ix_citas_moto_fecha', 'citas', 'moto_id, fecha', True),
        ('ix_facturas_taller_idempotencia', 'facturas', 'taller_id, clave_idempotencia', True),
        ('ix_ordenes_taller_idempotencia', 'ordenes_servicio', 'taller_id, clave_idempotencia', True),
    ]
    for nombre, tabla, columnas, unico in indices:
        _crear_indice(nombre, tabla, columnas, unico)

    if db.engine.dialect.name == 'postgresql':
        nulos = db.session.execute(text(
            'SELECT COUNT(*) FROM diagnosticos WHERE moto_id IS NULL'
        )).scalar()
        if nulos == 0:
            try:
                db.session.execute(text(
                    'ALTER TABLE diagnosticos ALTER COLUMN moto_id SET NOT NULL'
                ))
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
        else:
            logger.warning(
                'Hay %s diagnósticos sin moto. Corrígelos antes de aplicar NOT NULL.',
                nulos,
            )


def inicializar_base():
    db.create_all()
    _migrar_esquema()
    columnas_requeridas = {
        'usuarios': {'taller_id', 'nombre', 'token_version', 'activo'},
        'clientes': {'taller_id'},
        'motos': {'taller_id', 'transferida', 'cliente_id'},
        'inventario': {'taller_id'},
        'diagnosticos': {'taller_id', 'moto_id'},
        'citas': {'taller_id', 'moto_id'},
        'facturas': {'taller_id', 'moto_id', 'secuencia'},
        'ordenes_servicio': {'taller_id', 'moto_id', 'secuencia'},
        'ordenes_repuestos': {'orden_id', 'inventario_id'},
        'registros_pendientes': {'tipo', 'taller_id', 'taller_origen_id'},
        'auditoria': {'entidad', 'accion'},
    }
    inspector = inspect(db.engine)
    for tabla, requeridas in columnas_requeridas.items():
        existentes = {columna['name'] for columna in inspector.get_columns(tabla)}
        faltantes = requeridas - existentes
        if faltantes:
            raise RuntimeError(
                f'La tabla {tabla} tiene un esquema incompatible. '
                f'Faltan columnas: {", ".join(sorted(faltantes))}. '
                'Ejecuta el comando de reinicio autorizado o aplica la migración correspondiente.'
            )
    indices_motos = {indice['name'] for indice in inspector.get_indexes('motos')}
    if 'uq_motos_taller_placa_activa' not in indices_motos:
        raise RuntimeError(
            'La tabla motos necesita el índice multi-taller actualizado. '
            'Ejecuta el reinicio autorizado: flask --app app reiniciar-base-talleres --confirmar'
        )


@click.command('reiniciar-base-talleres')
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
    # El runner de pruebas y algunos invocadores de Click no abren un contexto
    # de aplicación; la sesión de SQLAlchemy lo necesita explícitamente.
    with app.app_context():
        db.drop_all()
        db.create_all()
        _migrar_esquema()
    click.echo('Base de datos reiniciada con el esquema multi-taller vacío.')


app.cli.add_command(reiniciar_base_talleres)


@click.command('crear-admin')
@click.option('--email', required=True, help='Correo de la cuenta administradora.')
@click.option(
    '--password',
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help='Contraseña de la cuenta administradora.',
)
@click.option('--taller-id', type=int, required=True, help='Taller sobre el que administrará.')
def crear_admin(email, password, taller_id):
    """Crea o promueve una cuenta con rol administrador."""
    with app.app_context():
        try:
            correo = email_valor(email)
            clave = validar_password(password)
        except ErrorValidacion as error:
            raise click.ClickException(error.mensaje) from None
        taller = db.session.get(Taller, taller_id)
        if taller is None:
            raise click.ClickException(f'El taller {taller_id} no existe.')
        usuario = Usuario.query.filter_by(username=correo).first()
        creado = usuario is None
        if usuario is None:
            usuario = Usuario(
                username=correo,
                rol='admin',
                nombre=correo.split('@')[0],
                taller_id=taller_id,
                email_verificado=True,
            )
            db.session.add(usuario)
        else:
            usuario.rol = 'admin'
            usuario.taller_id = taller_id
            usuario.activo = True
            usuario.email_verificado = True
        usuario.set_password(clave)
        db.session.flush()
        registrar_auditoria(
            'usuario', usuario.id, 'crear_admin' if creado else 'promover_admin',
            despues={'email': correo, 'taller_id': taller_id},
            usuario_id=usuario.id, taller_id=taller_id,
        )
        db.session.commit()
        click.echo(
            f"Cuenta administradora {'creada' if creado else 'actualizada'}: {correo} "
            f'(taller {taller_id}).'
        )


app.cli.add_command(crear_admin)


@click.command('procesar-ocr')
@click.option('--una-vez', is_flag=True, help='Procesa la cola actual y termina.')
@click.option('--intervalo', type=float, default=2.0, show_default=True,
              help='Segundos de espera cuando no hay trabajos.')
@click.option('--max-trabajos', type=int, default=0, show_default=True,
              help='Cantidad máxima de trabajos antes de salir (0 = sin límite).')
def procesar_ocr(una_vez, intervalo, max_trabajos):
    """Worker de la cola persistente de OCR."""
    with app.app_context():
        procesados = ejecutar_worker(
            intervalo=intervalo,
            max_trabajos=max(0, max_trabajos),
            una_vez=una_vez,
        )
    click.echo(f'Trabajos OCR procesados: {procesados}')


app.cli.add_command(procesar_ocr)


@click.command('limpiar-ocr')
@click.option('--dias', type=int, default=90, show_default=True,
              help='Antigüedad mínima de los trabajos terminados a eliminar.')
def limpiar_ocr(dias):
    """Elimina trabajos OCR terminados antiguos y sus imágenes residuales."""
    with app.app_context():
        eliminados = limpiar_trabajos(dias)
    click.echo(f'Trabajos OCR eliminados: {eliminados}')


app.cli.add_command(limpiar_ocr)


@click.command('aplicar-retencion')
@click.option('--auditoria-dias', type=int, default=None,
              help='Días de auditoría a conservar (por defecto MOTOSMART_RETENCION_AUDITORIA_DIAS).')
@click.option('--ocr-dias', type=int, default=None,
              help='Días de trabajos OCR terminados a conservar.')
@click.option('--dry-run', is_flag=True, help='Solo cuenta lo que se eliminaría.')
def aplicar_retencion_cli(auditoria_dias, ocr_dias, dry_run):
    """Aplica la política de retención de datos configurada."""
    with app.app_context():
        resumen = aplicar_retencion(
            dias_auditoria=auditoria_dias,
            dias_ocr=ocr_dias,
            dry_run=dry_run,
        )
    modo = 'simulación' if dry_run else 'aplicado'
    click.echo(f'Retención ({modo}): {resumen}')


app.cli.add_command(aplicar_retencion_cli)


@click.command('exportar-usuario')
@click.option('--email', required=True, help='Correo de la cuenta a exportar.')
@click.option('--salida', required=True, type=click.Path(dir_okay=False),
              help='Ruta del archivo JSON de salida.')
def exportar_usuario_cli(email, salida):
    """Exporta los datos personales de una cuenta (soporte/legal)."""
    with app.app_context():
        usuario = Usuario.query.filter_by(username=email.strip().lower()).first()
        if usuario is None:
            raise click.ClickException('La cuenta no existe.')
        exportar_json(usuario, salida)
    click.echo(f'Datos exportados en {salida}')


app.cli.add_command(exportar_usuario_cli)


@click.command('anonimizar-usuario')
@click.option('--email', required=True, help='Correo de la cuenta a anonimizar.')
@click.option('--motivo', default='solicitud_administrativa', show_default=True,
              help='Motivo registrado en la auditoría.')
@click.option('--taller-id', type=int, default=None,
              help='Limita la anonimización a un taller concreto (personal del taller).')
@click.option('--forzar', is_flag=True,
              help='Permite anonimizar una cuenta titular del taller.')
def anonimizar_usuario_cli(email, motivo, taller_id, forzar):
    """Anonimiza una cuenta por solicitud legal o administrativa."""
    with app.app_context():
        usuario = Usuario.query.filter_by(username=email.strip().lower()).first()
        if usuario is None:
            raise click.ClickException('La cuenta no existe.')
        try:
            resumen = anonimizar_usuario(
                usuario, motivo=motivo, actor_id=usuario.id, forzar=forzar,
                taller_id=taller_id,
            )
        except ErrorPrivacidad as error:
            db.session.rollback()
            raise click.ClickException(error.mensaje) from None
        db.session.commit()
    click.echo(f'Cuenta anonimizada: {resumen}')


app.cli.add_command(anonimizar_usuario_cli)


if __name__ == '__main__':
    if app.config.get('MOTOSMART_AUTO_MIGRATE'):
        with app.app_context():
            inicializar_base()
        if app.config.get('MOTOSMART_OCR_INLINE_WORKER'):
            iniciar_trabajador_en_hilo(app)
    if ES_PRODUCCION:
        from waitress import serve
        serve(
            app,
            host=os.environ.get('MOTOSMART_HOST', '127.0.0.1'),
            port=int(os.environ.get('MOTOSMART_PORT', '8000')),
            threads=max(1, int(os.environ.get('MOTOSMART_THREADS', '8'))),
        )
    else:
        app.run(debug=os.environ.get('MOTOSMART_DEBUG', 'false').lower() in ('1', 'true', 'yes'))
