import hashlib
import json
import secrets
import time
from urllib.parse import quote

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    set_access_cookies,
    unset_jwt_cookies,
)
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from db import db
from modelo.clientes import Cliente
from modelo.diagnostico import Diagnostico
from modelo.moto import Moto
from modelo.registro_pendiente import RegistroPendiente
from modelo.taller import Taller
from modelo.usuario import Usuario
from services.notificaciones import enviar_correo
from services.privacidad import ErrorPrivacidad, anonimizar_usuario, exportar_datos
from services.seguridad import limitar, registrar_auditoria
from services.tenencia import usuario_actual
from services.validacion import (
    ErrorValidacion,
    cuerpo_json,
    email_valor,
    entero,
    password as validar_password,
    texto,
)


auth_bp = Blueprint('auth', __name__)
REGISTRO_EXPIRA_SEGUNDOS = 30 * 60

# Hash de referencia para que un correo inexistente tarde un tiempo similar a
# uno existente y no permita enumerar cuentas por temporización.
_DUMMY_HASH = generate_password_hash('motorsmart-timing-defensa-2026')


def token_usuario(usuario):
    return create_access_token(
        identity=str(usuario.id),
        additional_claims={
            'rol': usuario.rol,
            'taller_id': usuario.taller_id,
            'nombre': usuario.nombre or usuario.username.split('@')[0],
            'tv': int(usuario.token_version or 0),
            'es_titular_taller': (
                usuario.rol == 'mecanico' and usuario.creado_por_id is None
            ),
        },
    )


def datos_usuario(usuario):
    """Datos no sensibles que el frontend usa para pintar la sesión."""
    return {
        'email': usuario.username,
        'rol': usuario.rol,
        'nombre': usuario.nombre or usuario.username.split('@')[0],
        'taller_id': usuario.taller_id,
        'es_titular': usuario.rol == 'mecanico' and usuario.creado_por_id is None,
        'email_verificado': bool(usuario.email_verificado),
    }


def respuesta_con_sesion(payload, usuario, *, status=200):
    """Responde y renueva la cookie HttpOnly + el token CSRF.

    El token solo se incluye en el cuerpo si se habilita explícitamente para
    integraciones locales; en producción el navegador nunca lo ve.
    """
    token = token_usuario(usuario)
    cuerpo = dict(payload)
    if current_app.config.get('MOTOSMART_RETURN_TOKEN_IN_BODY', False):
        cuerpo['token'] = token
    respuesta = jsonify(cuerpo)
    respuesta.status_code = status
    set_access_cookies(respuesta, token)
    return respuesta


def crear_verificacion(email, asunto, mensaje, tipo, taller_id, usuario_id=None,
                       taller_origen_id=None, nombre=None, password_hash=None,
                       datos=None):
    token = secrets.token_urlsafe(32)
    ahora = int(time.time())
    RegistroPendiente.query.filter(
        RegistroPendiente.expires_at <= ahora
    ).delete(synchronize_session=False)
    registro = RegistroPendiente.query.filter_by(email=email, tipo=tipo).first()
    if registro:
        if registro.expires_at > ahora:
            return None, 'Ya hay una verificación pendiente para ese correo.'
        db.session.delete(registro)
        db.session.flush()
    registro = RegistroPendiente(
        email=email,
        nombre=nombre,
        usuario_id=usuario_id,
        password_hash=password_hash,
        tipo=tipo,
        taller_id=taller_id,
        taller_origen_id=taller_origen_id,
        datos=datos,
        token_hash=hashlib.sha256(token.encode('utf-8')).hexdigest(),
        expires_at=ahora + REGISTRO_EXPIRA_SEGUNDOS,
    )
    db.session.add(registro)
    db.session.commit()
    if tipo == 'transferencia':
        tipo_enlace = 'transfer'
    elif tipo == 'correo':
        tipo_enlace = 'email'
    elif tipo == 'mecanico':
        tipo_enlace = 'invite'
    elif tipo == 'recuperacion':
        tipo_enlace = 'reset'
    elif tipo == 'taller':
        tipo_enlace = 'taller'
    else:
        tipo_enlace = 'claim'
    enlace = (
        f"{current_app.config['MOTOSMART_PUBLIC_URL']}/verificar-registro"
        f"#{tipo_enlace}={quote(token, safe='')}"
    )
    if not enviar_correo(email, asunto, f'{mensaje}\n\n{enlace}\n\nEl enlace vence en 30 minutos.'):
        db.session.delete(registro)
        db.session.commit()
        return None, 'No se pudo enviar el correo de verificación. Revisa la configuración SMTP e inténtalo de nuevo.'
    return registro, None


def _requiere_verificacion():
    return bool(current_app.config.get('MOTOSMART_REQUIRE_EMAIL_VERIFICATION'))


@auth_bp.route('/talleres', methods=['GET'])
@limitar(120, 60, nombre='talleres')
def listar_talleres():
    talleres = Taller.query.order_by(Taller.nombre.asc(), Taller.ciudad.asc()).all()
    return jsonify([
        {'id': taller.id, 'nombre': taller.nombre, 'ciudad': taller.ciudad}
        for taller in talleres
    ])


@auth_bp.route('/talleres', methods=['POST'])
@limitar(10, 3600, nombre='crear_taller')
def crear_taller():
    data = cuerpo_json()
    nombre = texto(data, 'nombre', maximo=100)
    ciudad = texto(data, 'ciudad', maximo=80)
    telefono = texto(data, 'telefono', maximo=20)
    nombre_titular = texto(data, 'nombre_titular', maximo=100)
    email = email_valor(data.get('email'))
    clave = validar_password(data.get('password'))

    if Usuario.query.filter_by(username=email).first():
        return jsonify({'error': 'Ya existe una cuenta con ese correo.'}), 409
    # No permitir consumir la identidad de un cliente histórico de otro taller.
    if Cliente.query.filter_by(email=email).first():
        return jsonify({
            'error': 'Ese correo ya está asociado a un cliente. Inicia sesión o regístrate como cliente.'
        }), 409
    if RegistroPendiente.query.filter_by(email=email).filter(
        RegistroPendiente.expires_at > int(time.time())
    ).first():
        return jsonify({'error': 'Ese correo tiene una verificación pendiente.'}), 409
    if Taller.query.filter_by(nombre=nombre, ciudad=ciudad).first():
        return jsonify({'error': 'Ya existe un taller con ese nombre en esa ciudad.'}), 409

    if _requiere_verificacion():
        datos = json.dumps({
            'nombre': nombre,
            'ciudad': ciudad,
            'telefono': telefono,
            'nombre_titular': nombre_titular,
        })
        _, error = crear_verificacion(
            email,
            'Confirma tu correo para crear tu taller en MotoSmart',
            f'Hola {nombre_titular}, confirma tu correo para crear '
            f'{nombre} en {ciudad}.',
            'taller',
            None,
            nombre=nombre_titular,
            password_hash=generate_password_hash(clave),
            datos=datos,
        )
        if error:
            return jsonify({'error': error}), 503
        return jsonify({
            'mensaje': 'Te enviamos un enlace para confirmar tu correo y crear el taller.'
        }), 202

    taller = Taller(nombre=nombre, ciudad=ciudad, telefono=telefono)
    db.session.add(taller)
    db.session.flush()
    titular = Usuario(
        username=email,
        rol='mecanico',
        nombre=nombre_titular,
        taller_id=taller.id,
        email_verificado=True,
    )
    titular.set_password(clave)
    db.session.add(titular)
    db.session.flush()
    registrar_auditoria('taller', taller.id, 'crear', despues={
        'nombre': taller.nombre, 'ciudad': taller.ciudad, 'titular': email,
    }, usuario_id=titular.id, taller_id=taller.id)
    db.session.commit()
    return respuesta_con_sesion({
        'mensaje': 'Taller creado. Ya puedes comenzar a gestionarlo.',
        'usuario': datos_usuario(titular),
        'taller': {'id': taller.id, 'nombre': taller.nombre, 'ciudad': taller.ciudad},
    }, titular, status=201)


@auth_bp.route('/register', methods=['POST'])
@limitar(20, 3600, nombre='register')
def register():
    data = cuerpo_json()
    username = email_valor(data.get('username'))
    clave = validar_password(data.get('password'))
    nombre = texto(data, 'nombre', maximo=100)
    taller_id = entero(data, 'taller_id', minimo=1)
    taller = db.session.get(Taller, taller_id)
    if not taller:
        return jsonify({'mensaje': 'El taller seleccionado no existe.'}), 404
    if Usuario.query.filter_by(username=username).first():
        return jsonify({'mensaje': 'Ya existe una cuenta con ese correo.'}), 409

    cliente = Cliente.query.filter_by(email=username, taller_id=taller.id).first()
    if cliente:
        usuario_pendiente = Usuario(
            username=username,
            rol='cliente',
            nombre=nombre,
            taller_id=taller.id,
        )
        usuario_pendiente.set_password(clave)
        registro, error = crear_verificacion(
            username,
            'Verifica tu correo para reclamar tus datos de MotoSmart',
            f'Hola {nombre}, este correo ya tiene datos en {taller.nombre}. '
            'Confirma que te pertenecen para conectarlos a tu cuenta.',
            'registro',
            taller.id,
            nombre=nombre,
            password_hash=usuario_pendiente.password_hash,
        )
        if error:
            status = 409 if 'pendiente' in error else 503
            return jsonify({'mensaje': error}), status
        return jsonify({
            'mensaje': 'Ese correo ya tiene datos en el taller. Te enviamos un enlace para verificarlo.'
        }), 202

    if _requiere_verificacion():
        usuario_pendiente = Usuario(
            username=username,
            rol='cliente',
            nombre=nombre,
            taller_id=taller.id,
        )
        usuario_pendiente.set_password(clave)
        _, error = crear_verificacion(
            username,
            'Confirma tu correo para crear tu cuenta MotoSmart',
            f'Hola {nombre}, confirma tu correo para crear tu cuenta en {taller.nombre}.',
            'registro_nuevo',
            taller.id,
            nombre=nombre,
            password_hash=usuario_pendiente.password_hash,
        )
        if error:
            return jsonify({'mensaje': error}), 503
        return jsonify({
            'mensaje': 'Te enviamos un enlace para confirmar tu correo y crear la cuenta.'
        }), 202

    usuario = Usuario(
        username=username,
        rol='cliente',
        nombre=nombre,
        taller_id=taller.id,
        email_verificado=True,
    )
    usuario.set_password(clave)
    db.session.add(usuario)
    db.session.add(Cliente(nombre=nombre, email=username, taller_id=taller.id))
    db.session.commit()
    return jsonify({'mensaje': 'Cuenta creada. Ya puedes iniciar sesión.'}), 201


@auth_bp.route('/verificar-registro', methods=['GET'])
def pagina_verificar_registro():
    return render_template('verify_registration.html')


def _crear_taller_pendiente(registro):
    """Crea el taller y su titular cuando se confirma el correo."""
    try:
        datos = json.loads(registro.datos or '{}')
    except (TypeError, ValueError):
        datos = {}
    nombre = str(datos.get('nombre') or '').strip()
    ciudad = str(datos.get('ciudad') or '').strip()
    telefono = str(datos.get('telefono') or '').strip()
    nombre_titular = str(datos.get('nombre_titular') or registro.nombre or '').strip()
    if not nombre or not ciudad or not telefono or not nombre_titular or not registro.password_hash:
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'La solicitud de creación del taller ya no es válida.'}), 409
    if Usuario.query.filter_by(username=registro.email).first():
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'Ya existe una cuenta con ese correo.'}), 409
    if Taller.query.filter_by(nombre=nombre, ciudad=ciudad).first():
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'Ya existe un taller con ese nombre en esa ciudad.'}), 409

    taller = Taller(nombre=nombre, ciudad=ciudad, telefono=telefono)
    db.session.add(taller)
    db.session.flush()
    titular = Usuario(
        username=registro.email,
        rol='mecanico',
        nombre=nombre_titular,
        taller_id=taller.id,
        email_verificado=True,
    )
    titular.password_hash = registro.password_hash
    db.session.add(titular)
    db.session.flush()
    registrar_auditoria('taller', taller.id, 'crear', despues={
        'nombre': taller.nombre, 'ciudad': taller.ciudad, 'titular': registro.email,
    }, usuario_id=titular.id, taller_id=taller.id)
    db.session.delete(registro)
    db.session.commit()
    return jsonify({
        'mensaje': 'Correo verificado. Tu taller ya está creado; inicia sesión para gestionarlo.'
    }), 201


def _crear_usuario_cliente(registro):
    if Usuario.query.filter_by(username=registro.email).first():
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'Ya existe una cuenta con ese correo.'}), 409
    usuario = Usuario(
        username=registro.email,
        rol='cliente',
        nombre=registro.nombre,
        taller_id=registro.taller_id,
        email_verificado=True,
    )
    usuario.password_hash = registro.password_hash
    cliente = Cliente.query.filter_by(
        email=registro.email,
        taller_id=registro.taller_id,
    ).first()
    if cliente:
        cliente.nombre = registro.nombre
    else:
        db.session.add(Cliente(
            nombre=registro.nombre,
            email=registro.email,
            taller_id=registro.taller_id,
        ))
    db.session.add(usuario)
    db.session.delete(registro)
    db.session.commit()
    return jsonify({
        'mensaje': 'Correo verificado. Tu cuenta ya está conectada con los datos del taller; inicia sesión.'
    }), 201


def _crear_usuario_mecanico(registro, data):
    titular = db.session.get(Usuario, registro.usuario_id) if registro.usuario_id else None
    if not titular or titular.rol != 'mecanico' or titular.creado_por_id is not None:
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'La invitación ya no es válida.'}), 409
    if Usuario.query.filter_by(username=registro.email).first():
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'Ya existe una cuenta con ese correo.'}), 409
    clave = validar_password(data.get('password'))
    usuario = Usuario(
        username=registro.email,
        rol='mecanico',
        nombre=registro.nombre or registro.email.split('@')[0],
        taller_id=registro.taller_id,
        creado_por_id=titular.id,
        email_verificado=True,
    )
    usuario.set_password(clave)
    db.session.add(usuario)
    db.session.flush()
    registrar_auditoria('usuario', usuario.id, 'crear_mecanico', despues={
        'email': usuario.username, 'taller_id': usuario.taller_id,
    }, usuario_id=titular.id, taller_id=titular.taller_id)
    db.session.delete(registro)
    db.session.commit()
    return jsonify({
        'mensaje': 'Invitación aceptada. Ya puedes iniciar sesión como mecánico.'
    }), 201


def verificar_transferencia(registro):
    usuario = db.session.get(Usuario, registro.usuario_id)
    taller_destino = db.session.get(Taller, registro.taller_id)
    if (
        not usuario
        or not taller_destino
        or usuario.taller_id != registro.taller_origen_id
        or usuario.rol != 'cliente'
    ):
        return jsonify({'mensaje': 'La solicitud de cambio de taller ya no es válida.'}), 409

    cliente_origen = Cliente.query.filter_by(
        email=usuario.username,
        taller_id=usuario.taller_id,
    ).first()
    if not cliente_origen:
        return jsonify({'mensaje': 'No se encontró el perfil de cliente del taller de origen.'}), 404

    motos_origen = Moto.query.filter_by(
        cliente_id=cliente_origen.id,
        taller_id=usuario.taller_id,
        transferida=False,
    ).with_for_update().all()
    cliente_destino = Cliente.query.filter_by(
        email=usuario.username,
        taller_id=taller_destino.id,
    ).first()
    for moto in motos_origen:
        moto_destino = Moto.query.filter_by(
            placa=moto.placa,
            taller_id=taller_destino.id,
        ).first()
        if moto_destino and (
            not cliente_destino or moto_destino.cliente_id != cliente_destino.id
        ):
            db.session.delete(registro)
            db.session.commit()
            return jsonify({
                'mensaje': (
                    f'La placa {moto.placa} ya está registrada en el taller de destino. '
                    'Contacta al taller para resolverlo antes de solicitar la mudanza.'
                )
            }), 409

    if not cliente_destino:
        cliente_destino = Cliente(
            nombre=cliente_origen.nombre,
            email=usuario.username,
            telefono=cliente_origen.telefono,
            taller_id=taller_destino.id,
        )
        db.session.add(cliente_destino)
        db.session.flush()

    for moto in motos_origen:
        diagnosticos = (
            Diagnostico.query
            .filter_by(moto_id=moto.id, taller_id=usuario.taller_id)
            .order_by(Diagnostico.fecha.desc(), Diagnostico.id.desc())
            .limit(3)
            .all()
        )
        moto_destino = Moto.query.filter_by(
            placa=moto.placa,
            taller_id=taller_destino.id,
        ).first()
        if moto_destino:
            moto_destino.marca = moto.marca
            moto_destino.modelo = moto.modelo
            moto_destino.tipo_tecnologia = moto.tipo_tecnologia
            moto_destino.transferida = False
        else:
            moto_destino = Moto(
                placa=moto.placa,
                marca=moto.marca,
                modelo=moto.modelo,
                tipo_tecnologia=moto.tipo_tecnologia,
                cliente_id=cliente_destino.id,
                taller_id=taller_destino.id,
            )
            db.session.add(moto_destino)
            db.session.flush()
        existentes = Diagnostico.query.filter_by(
            moto_id=moto_destino.id,
            taller_id=taller_destino.id,
        ).all()
        firmas_existentes = {
            (
                item.codigo_error, item.descripcion, item.detalle_codigos,
                item.prioridad, item.motivo_prioridad, item.recomendacion, item.fecha,
            )
            for item in existentes
        }
        for diagnostico in diagnosticos:
            firma = (
                diagnostico.codigo_error, diagnostico.descripcion,
                diagnostico.detalle_codigos, diagnostico.prioridad,
                diagnostico.motivo_prioridad, diagnostico.recomendacion,
                diagnostico.fecha,
            )
            if firma in firmas_existentes:
                continue
            db.session.add(Diagnostico(
                moto_id=moto_destino.id,
                taller_id=taller_destino.id,
                codigo_error=diagnostico.codigo_error,
                descripcion=diagnostico.descripcion,
                detalle_codigos=diagnostico.detalle_codigos,
                prioridad=diagnostico.prioridad,
                motivo_prioridad=diagnostico.motivo_prioridad,
                recomendacion=diagnostico.recomendacion,
                fecha=diagnostico.fecha,
            ))
            firmas_existentes.add(firma)
        moto.transferida = True

    usuario.taller_id = taller_destino.id
    db.session.delete(registro)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'mensaje': 'No fue posible completar la mudanza porque una placa ya está registrada en el taller de destino.'
        }), 409
    return jsonify({
        'mensaje': 'Cambio de taller confirmado. Tus motos y sus tres diagnósticos más recientes ya están en el nuevo taller. Citas, órdenes y facturas anteriores permanecen en el taller de origen.'
    }), 200


@auth_bp.route('/register/verify', methods=['POST'])
@limitar(60, 3600, nombre='verificar_registro')
def verificar_registro():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    if not isinstance(token, str) or not token.strip():
        return jsonify({'mensaje': 'El enlace no es válido o venció. Solicita uno nuevo.'}), 400
    token_hash = hashlib.sha256(token.strip().encode('utf-8')).hexdigest()
    ahora = int(time.time())
    registro = RegistroPendiente.query.filter_by(token_hash=token_hash).first()
    if not registro or registro.expires_at <= ahora:
        if registro:
            db.session.delete(registro)
            db.session.commit()
        return jsonify({'mensaje': 'El enlace no es válido o venció. Solicita uno nuevo.'}), 400
    if registro.tipo == 'transferencia':
        return verificar_transferencia(registro)
    if registro.tipo == 'mecanico':
        return _crear_usuario_mecanico(registro, data)
    if registro.tipo == 'taller':
        return _crear_taller_pendiente(registro)
    if registro.tipo not in ('registro', 'registro_nuevo') or not registro.password_hash or not registro.taller_id:
        return jsonify({'mensaje': 'El enlace no corresponde a un registro válido.'}), 400
    return _crear_usuario_cliente(registro)


@auth_bp.route('/mi-cuenta/verificar-email', methods=['POST'])
@limitar(60, 3600, nombre='verificar_email')
def verificar_cambio_correo():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    if not isinstance(token, str) or not token.strip():
        return jsonify({'mensaje': 'El enlace no es válido o venció. Solicita un nuevo cambio.'}), 400
    token_hash = hashlib.sha256(token.strip().encode('utf-8')).hexdigest()
    ahora = int(time.time())
    registro = RegistroPendiente.query.filter_by(token_hash=token_hash).first()
    if (
        not registro
        or registro.tipo != 'correo'
        or registro.usuario_id is None
        or registro.expires_at <= ahora
    ):
        if registro and registro.expires_at <= ahora:
            db.session.delete(registro)
            db.session.commit()
        return jsonify({'mensaje': 'El enlace no es válido o venció. Solicita un nuevo cambio.'}), 400

    usuario = db.session.get(Usuario, registro.usuario_id)
    if not usuario:
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'La cuenta asociada ya no existe.'}), 404
    if Usuario.query.filter(
        Usuario.username == registro.email,
        Usuario.id != usuario.id,
    ).first():
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'Ya existe una cuenta con ese correo.'}), 409

    cliente_actual = Cliente.query.filter_by(
        email=usuario.username,
        taller_id=usuario.taller_id,
    ).first()
    cliente_destino = Cliente.query.filter_by(
        email=registro.email,
        taller_id=usuario.taller_id,
    ).first()
    if cliente_actual and cliente_destino and cliente_actual.id != cliente_destino.id:
        Moto.query.filter_by(
            cliente_id=cliente_actual.id,
            taller_id=usuario.taller_id,
        ).update({Moto.cliente_id: cliente_destino.id}, synchronize_session=False)
        db.session.delete(cliente_actual)
    elif cliente_actual:
        cliente_actual.email = registro.email

    usuario.username = registro.email
    usuario.token_version = int(usuario.token_version or 0) + 1
    registrar_auditoria('usuario', usuario.id, 'cambiar_email', despues={
        'email': usuario.username,
    })
    db.session.delete(registro)
    db.session.commit()
    return jsonify({
        'mensaje': 'Correo verificado y actualizado. Ya puedes iniciar sesión con la nueva dirección.'
    }), 200


@auth_bp.route('/mi-cuenta/recuperar', methods=['POST'])
@limitar(5, 3600, por='email', nombre='recuperar_password')
def recuperar_password():
    """Envía un enlace de restablecimiento sin revelar si el correo existe."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    try:
        correo = email_valor(data.get('email'))
    except ErrorValidacion:
        correo = None
    if correo:
        usuario = Usuario.query.filter_by(username=correo).first()
        if usuario and usuario.activo:
            _, error = crear_verificacion(
                correo,
                'Restablece tu contraseña de MotoSmart',
                'Recibimos una solicitud para restablecer tu contraseña. '
                'Si no fuiste tú, ignora este mensaje.',
                'recuperacion',
                usuario.taller_id,
                usuario_id=usuario.id,
            )
            if error:
                current_app.logger.warning(
                    'No se pudo enviar el correo de recuperación: %s', error
                )
    return jsonify({
        'mensaje': 'Si el correo existe, enviamos un enlace para restablecer la contraseña.'
    }), 202


@auth_bp.route('/mi-cuenta/restablecer', methods=['POST'])
@limitar(10, 3600, nombre='restablecer_password')
def restablecer_password():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    token = data.get('token')
    if not isinstance(token, str) or not token.strip():
        return jsonify({'mensaje': 'El enlace no es válido o venció. Solicita uno nuevo.'}), 400
    clave = validar_password(data.get('password'))
    token_hash = hashlib.sha256(token.strip().encode('utf-8')).hexdigest()
    ahora = int(time.time())
    registro = RegistroPendiente.query.filter_by(token_hash=token_hash).first()
    if (
        not registro
        or registro.tipo != 'recuperacion'
        or registro.usuario_id is None
        or registro.expires_at <= ahora
    ):
        if registro and registro.expires_at <= ahora:
            db.session.delete(registro)
            db.session.commit()
        return jsonify({'mensaje': 'El enlace no es válido o venció. Solicita uno nuevo.'}), 400

    usuario = db.session.get(Usuario, registro.usuario_id)
    if not usuario or not usuario.activo:
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'La cuenta asociada ya no está disponible.'}), 404

    usuario.set_password(clave)
    usuario.token_version = int(usuario.token_version or 0) + 1
    registrar_auditoria('usuario', usuario.id, 'restablecer_password', despues={
        'email': usuario.username,
    })
    db.session.delete(registro)
    db.session.commit()
    return jsonify({
        'mensaje': 'Contraseña restablecida. Ya puedes iniciar sesión con tu nueva contraseña.'
    }), 200


@auth_bp.route('/login', methods=['POST'])
@limitar(30, 60, por='email', nombre='login')
def login():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'mensaje': 'Credenciales inválidas'}), 401
    try:
        username = email_valor(data.get('username'))
    except ErrorValidacion:
        return jsonify({'mensaje': 'Credenciales inválidas'}), 401
    clave = data.get('password')
    usuario = Usuario.query.filter_by(username=username).first()
    if usuario is None:
        check_password_hash(_DUMMY_HASH, str(clave or ''))
        return jsonify({'mensaje': 'Credenciales inválidas'}), 401
    if not usuario.activo:
        return jsonify({'mensaje': 'La cuenta está desactivada.'}), 403
    if not usuario.check_password(str(clave or '')):
        return jsonify({'mensaje': 'Credenciales inválidas'}), 401
    return respuesta_con_sesion({
        'mensaje': 'Login exitoso',
        'usuario': datos_usuario(usuario),
    }, usuario, status=200)


@auth_bp.route('/sesion', methods=['GET'])
@jwt_required()
@limitar(120, 60, nombre='sesion')
def sesion():
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'La cuenta asociada ya no existe.'}), 401
    return jsonify({'usuario': datos_usuario(usuario)})


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    usuario = usuario_actual()
    if usuario:
        usuario.token_version = int(usuario.token_version or 0) + 1
        registrar_auditoria('usuario', usuario.id, 'logout')
        db.session.commit()
    respuesta = jsonify({'mensaje': 'Sesión cerrada.'})
    unset_jwt_cookies(respuesta)
    return respuesta


@auth_bp.route('/mi-cuenta/cambiar-taller', methods=['POST'])
@jwt_required()
@limitar(5, 3600, por='usuario', nombre='cambiar_taller')
def solicitar_cambio_taller():
    usuario = usuario_actual()
    if not usuario or usuario.rol != 'cliente':
        return jsonify({'error': 'Solo los clientes pueden cambiar de taller.'}), 403
    data = cuerpo_json()
    taller_id = entero(data, 'taller_id', minimo=1)
    if taller_id == usuario.taller_id:
        return jsonify({'error': 'Ya perteneces a ese taller.'}), 400
    taller = db.session.get(Taller, taller_id)
    if not taller:
        return jsonify({'error': 'El taller seleccionado no existe.'}), 404

    _, error = crear_verificacion(
        usuario.username,
        'Confirma tu cambio de taller en MotoSmart',
        f'Solicitaste trasladar tus motos desde tu taller actual a {taller.nombre}.',
        'transferencia',
        taller.id,
        usuario_id=usuario.id,
        taller_origen_id=usuario.taller_id,
    )
    if error:
        status = 409 if 'pendiente' in error else 503
        return jsonify({'error': error}), status
    return jsonify({
        'mensaje': 'Te enviamos un enlace para confirmar el cambio de taller.'
    }), 202


@auth_bp.route('/mi-cuenta', methods=['GET', 'PUT'])
@jwt_required()
def mi_cuenta():
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'La cuenta asociada ya no existe.'}), 404
    if request.method == 'GET':
        taller = db.session.get(Taller, usuario.taller_id)
        return jsonify({
            'email': usuario.username,
            'rol': usuario.rol,
            'nombre': usuario.nombre or usuario.username.split('@')[0],
            'taller_id': usuario.taller_id,
            'taller_nombre': taller.nombre if taller else '',
            'es_titular': usuario.rol == 'mecanico' and usuario.creado_por_id is None,
            'email_verificado': bool(usuario.email_verificado),
        })

    data = cuerpo_json()
    email_solicitado = data.get('email')
    if email_solicitado is None:
        nuevo_email = usuario.username
    else:
        nuevo_email = email_valor(email_solicitado)
    clave_nueva = data.get('password')
    if clave_nueva in (None, ''):
        clave_nueva = None

    if nuevo_email != usuario.username:
        if clave_nueva:
            return jsonify({
                'error': 'Solicita primero el cambio de correo y actualiza la contraseña por separado.'
            }), 400
        if Usuario.query.filter(
            Usuario.username == nuevo_email,
            Usuario.id != usuario.id,
        ).first():
            return jsonify({'error': 'Ya existe una cuenta con ese correo.'}), 409
        _, error = crear_verificacion(
            nuevo_email,
            'Confirma el cambio de correo de tu cuenta MotoSmart',
            'Para confirmar que controlas esta nueva dirección de correo, abre este enlace:',
            'correo',
            usuario.taller_id,
            usuario_id=usuario.id,
        )
        if error:
            status = 409 if 'pendiente' in error else 503
            return jsonify({'error': error}), status
        return jsonify({
            'mensaje': 'Te enviamos un enlace para verificar la nueva dirección de correo.'
        }), 202

    if not clave_nueva:
        return jsonify({'mensaje': 'No hay cambios para aplicar.', 'email': usuario.username}), 200

    clave_actual = data.get('password_actual')
    if not isinstance(clave_actual, str) or not clave_actual:
        return jsonify({'error': 'Ingresa tu contraseña actual para cambiarla.'}), 400
    if not usuario.check_password(clave_actual):
        return jsonify({'error': 'La contraseña actual no es correcta.'}), 401

    validar_password(clave_nueva)
    usuario.set_password(clave_nueva)
    usuario.token_version = int(usuario.token_version or 0) + 1
    registrar_auditoria('usuario', usuario.id, 'cambiar_password', despues={
        'email': usuario.username,
    })
    db.session.commit()
    return respuesta_con_sesion({
        'mensaje': 'Contraseña actualizada. Tu sesión se renovó y las demás sesiones se cerraron.',
        'usuario': datos_usuario(usuario),
        'email': usuario.username,
    }, usuario, status=200)


@auth_bp.route('/mi-cuenta/exportar', methods=['GET'])
@jwt_required()
@limitar(10, 3600, por='usuario', nombre='exportar_cuenta')
def exportar_mi_cuenta():
    """Entrega una copia portable de los datos personales de la cuenta."""
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'La cuenta asociada ya no existe.'}), 404
    respuesta = jsonify(exportar_datos(usuario))
    respuesta.headers['Content-Disposition'] = (
        'attachment; filename="motosmart-datos-personales.json"'
    )
    return respuesta, 200


@auth_bp.route('/mi-cuenta', methods=['DELETE'])
@jwt_required()
@limitar(5, 3600, por='usuario', nombre='eliminar_cuenta')
def eliminar_mi_cuenta():
    """Anonimiza la cuenta por solicitud del titular (derecho al olvido)."""
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'La cuenta asociada ya no existe.'}), 404
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'error': 'El cuerpo debe ser un objeto JSON.'}), 400
    if data.get('confirmar') != 'ELIMINAR':
        return jsonify({
            'error': 'Para eliminar la cuenta envía {"confirmar": "ELIMINAR"}.'
        }), 400
    if not usuario.check_password(str(data.get('password') or '')):
        return jsonify({'error': 'La contraseña actual no es correcta.'}), 401
    try:
        resumen = anonimizar_usuario(
            usuario,
            motivo='solicitud_del_titular',
            actor_id=usuario.id,
        )
    except ErrorPrivacidad as error:
        db.session.rollback()
        return jsonify({'error': error.mensaje}), error.status
    db.session.commit()
    respuesta = jsonify({
        'mensaje': (
            'La cuenta fue eliminada y sus datos personales fueron anonimizados. '
            'Las facturas y órdenes exigidas por la normativa contable se conservan '
            'sin datos de contacto.'
        ),
        'resumen': resumen,
    })
    unset_jwt_cookies(respuesta)
    respuesta.status_code = 200
    return respuesta

