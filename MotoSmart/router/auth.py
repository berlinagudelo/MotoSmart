import hashlib
import secrets
import time
from urllib.parse import quote

from flask import Blueprint, request, jsonify, render_template, current_app
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
)
from sqlalchemy.exc import IntegrityError

from db import db
from modelo.clientes import Cliente
from modelo.diagnostico import Diagnostico
from modelo.moto import Moto
from modelo.registro_pendiente import RegistroPendiente
from modelo.taller import Taller
from modelo.usuario import Usuario
from services.notificaciones import enviar_correo
from services.tenencia import usuario_actual


auth_bp = Blueprint('auth', __name__)
REGISTRO_EXPIRA_SEGUNDOS = 30 * 60


def validar_correo_password(username, password):
    if not username or '@' not in username or len(username) > 50:
        return 'Ingresa un correo válido.'
    if len(password) < 6:
        return 'La contraseña debe tener al menos 6 caracteres.'
    return None


def token_usuario(usuario):
    return create_access_token(
        identity=str(usuario.id),
        additional_claims={
            'rol': usuario.rol,
            'taller_id': usuario.taller_id,
            'nombre': usuario.nombre or usuario.username.split('@')[0],
            'es_titular_taller': (
                usuario.rol == 'mecanico' and usuario.creado_por_id is None
            ),
        },
    )


def crear_verificacion(email, asunto, mensaje, tipo, taller_id, usuario_id=None,
                       taller_origen_id=None, nombre=None, password_hash=None):
    token = secrets.token_urlsafe(32)
    ahora = int(time.time())
    RegistroPendiente.query.filter(
        RegistroPendiente.expires_at <= ahora
    ).delete(synchronize_session=False)
    registro = RegistroPendiente.query.filter_by(email=email).first()
    if registro:
        if registro.expires_at > ahora:
            return None, 'Ya hay una verificación pendiente para ese correo.'
        db.session.delete(registro)
    registro = RegistroPendiente(
        email=email,
        nombre=nombre,
        usuario_id=usuario_id,
        password_hash=password_hash,
        tipo=tipo,
        taller_id=taller_id,
        taller_origen_id=taller_origen_id,
        token_hash=hashlib.sha256(token.encode('utf-8')).hexdigest(),
        expires_at=ahora + REGISTRO_EXPIRA_SEGUNDOS,
    )
    db.session.add(registro)
    db.session.commit()
    tipo_enlace = (
        'transfer' if tipo == 'transferencia'
        else 'email' if tipo == 'correo'
        else 'claim'
    )
    enlace = (
        f"{current_app.config['MOTOSMART_PUBLIC_URL']}/verificar-registro"
        f"#{tipo_enlace}={quote(token, safe='')}"
    )
    if not enviar_correo(email, asunto, f'{mensaje}\n\n{enlace}\n\nEl enlace vence en 30 minutos.'):
        db.session.delete(registro)
        db.session.commit()
        return None, 'No se pudo enviar el correo de verificación. Revisa la configuración SMTP e inténtalo de nuevo.'
    return registro, None


@auth_bp.route('/talleres', methods=['GET'])
def listar_talleres():
    talleres = Taller.query.order_by(Taller.nombre.asc(), Taller.ciudad.asc()).all()
    return jsonify([
        {'id': taller.id, 'nombre': taller.nombre, 'ciudad': taller.ciudad}
        for taller in talleres
    ])


@auth_bp.route('/talleres', methods=['POST'])
def crear_taller():
    data = request.get_json(silent=True) or {}
    nombre = str(data.get('nombre', '')).strip()
    ciudad = str(data.get('ciudad', '')).strip()
    telefono = str(data.get('telefono', '')).strip()
    nombre_titular = str(data.get('nombre_titular', '')).strip()
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    error = validar_correo_password(email, password)
    if error:
        return jsonify({'error': error}), 400
    if not nombre or len(nombre) > 100:
        return jsonify({'error': 'Ingresa un nombre de taller válido.'}), 400
    if not ciudad or len(ciudad) > 80:
        return jsonify({'error': 'Ingresa una ciudad válida.'}), 400
    if not telefono or len(telefono) > 20:
        return jsonify({'error': 'Ingresa un teléfono válido.'}), 400
    if not nombre_titular or len(nombre_titular) > 100:
        return jsonify({'error': 'Ingresa el nombre del titular.'}), 400
    if Usuario.query.filter_by(username=email).first():
        return jsonify({'error': 'Ya existe una cuenta con ese correo.'}), 409

    taller = Taller(nombre=nombre, ciudad=ciudad, telefono=telefono)
    db.session.add(taller)
    db.session.flush()
    titular = Usuario(
        username=email,
        rol='mecanico',
        nombre=nombre_titular,
        taller_id=taller.id,
    )
    titular.set_password(password)
    db.session.add(titular)
    db.session.commit()
    return jsonify({
        'mensaje': 'Taller creado. Ya puedes comenzar a gestionarlo.',
        'token': token_usuario(titular),
        'taller': {'id': taller.id, 'nombre': taller.nombre, 'ciudad': taller.ciudad},
    }), 201


@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip().lower()
    password = str(data.get('password', ''))
    error = validar_correo_password(username, password)
    if error:
        return jsonify({'mensaje': error}), 400
    if Usuario.query.filter_by(username=username).first():
        return jsonify({'mensaje': 'Ya existe una cuenta con ese correo.'}), 409
    nombre = str(data.get('nombre', '')).strip()
    if not nombre or len(nombre) > 100:
        return jsonify({'mensaje': 'Ingresa un nombre válido.'}), 400
    try:
        taller_id = int(data.get('taller_id'))
    except (TypeError, ValueError):
        return jsonify({'mensaje': 'Selecciona el taller al que perteneces.'}), 400
    taller = db.session.get(Taller, taller_id)
    if not taller:
        return jsonify({'mensaje': 'El taller seleccionado no existe.'}), 404

    cliente = Cliente.query.filter_by(email=username, taller_id=taller.id).first()
    if not cliente:
        usuario = Usuario(
            username=username,
            rol='cliente',
            nombre=nombre,
            taller_id=taller.id,
        )
        usuario.set_password(password)
        db.session.add(usuario)
        db.session.add(Cliente(nombre=nombre, email=username, taller_id=taller.id))
        db.session.commit()
        return jsonify({'mensaje': 'Cuenta creada. Ya puedes iniciar sesión.'}), 201

    usuario_pendiente = Usuario(
        username=username,
        rol='cliente',
        nombre=nombre,
        taller_id=taller.id,
    )
    usuario_pendiente.set_password(password)
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


@auth_bp.route('/verificar-registro', methods=['GET'])
def pagina_verificar_registro():
    return render_template('verify_registration.html')


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
def verificar_registro():
    data = request.get_json(silent=True) or {}
    token = str(data.get('token', ''))
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    ahora = int(time.time())
    registro = RegistroPendiente.query.filter_by(token_hash=token_hash).first()
    if not registro or registro.expires_at <= ahora:
        if registro:
            db.session.delete(registro)
            db.session.commit()
        return jsonify({'mensaje': 'El enlace no es válido o venció. Solicita uno nuevo.'}), 400
    if registro.tipo == 'transferencia':
        return verificar_transferencia(registro)
    if registro.tipo != 'registro' or not registro.password_hash or not registro.taller_id:
        return jsonify({'mensaje': 'El enlace no corresponde a un registro válido.'}), 400
    if Usuario.query.filter_by(username=registro.email).first():
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'Ya existe una cuenta con ese correo.'}), 409

    usuario = Usuario(
        username=registro.email,
        rol='cliente',
        nombre=registro.nombre,
        taller_id=registro.taller_id,
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


@auth_bp.route('/mi-cuenta/verificar-email', methods=['POST'])
def verificar_cambio_correo():
    data = request.get_json(silent=True) or {}
    token = str(data.get('token', ''))
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
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
    db.session.delete(registro)
    db.session.commit()
    return jsonify({
        'mensaje': 'Correo verificado y actualizado. Ya puedes iniciar sesión con la nueva dirección.'
    }), 200


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip().lower()
    usuario = Usuario.query.filter_by(username=username).first()
    if usuario and usuario.check_password(str(data.get('password', ''))):
        return jsonify({
            'mensaje': 'Login exitoso',
            'token': token_usuario(usuario),
        }), 200
    return jsonify({'mensaje': 'Credenciales inválidas'}), 401


@auth_bp.route('/mi-cuenta/cambiar-taller', methods=['POST'])
@jwt_required()
def solicitar_cambio_taller():
    usuario = usuario_actual()
    if not usuario or usuario.rol != 'cliente':
        return jsonify({'error': 'Solo los clientes pueden cambiar de taller.'}), 403
    data = request.get_json(silent=True) or {}
    try:
        taller_id = int(data.get('taller_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Selecciona el nuevo taller.'}), 400
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
        })

    data = request.get_json(silent=True) or {}
    email = str(data.get('email', usuario.username)).strip().lower()
    password = str(data.get('password', ''))
    if email and email != usuario.username:
        if '@' not in email or len(email) > 50:
            return jsonify({'error': 'Ingresa un correo electrónico válido.'}), 400
        if password:
            return jsonify({
                'error': 'Solicita primero el cambio de correo y actualiza la contraseña por separado.'
            }), 400
        if Usuario.query.filter(
            Usuario.username == email,
            Usuario.id != usuario.id,
        ).first():
            return jsonify({'error': 'Ya existe una cuenta con ese correo.'}), 400
        _, error = crear_verificacion(
            email,
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

    if password and len(password) < 6:
        return jsonify({'error': 'La contraseña debe tener al menos 6 caracteres.'}), 400
    if password:
        usuario.set_password(password)
    db.session.commit()
    return jsonify({'mensaje': 'Datos de la cuenta actualizados.', 'email': usuario.username})
