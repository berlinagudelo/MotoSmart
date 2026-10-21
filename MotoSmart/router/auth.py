import hashlib
import secrets
import time
from urllib.parse import quote

from flask import Blueprint, request, jsonify, render_template, current_app
from db import db
from modelo.usuario import Usuario
from modelo.clientes import Cliente
from modelo.moto import Moto
from modelo.registro_pendiente import RegistroPendiente
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from services.notificaciones import enviar_correo

auth_bp = Blueprint('auth', __name__)
REGISTRO_EXPIRA_SEGUNDOS = 30 * 60

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip().lower()
    if not username or '@' not in username or len(username) > 50:
        return jsonify({'mensaje': 'Ingresa un correo válido.'}), 400
    if Usuario.query.filter_by(username=username).first():
        return jsonify({"mensaje": "Usuario ya existe"}), 400

    tipo_cuenta = str(data.get('tipo_cuenta', 'cliente')).strip().lower()
    if tipo_cuenta != 'cliente':
        return jsonify({
            'mensaje': 'El titular del taller debe crearse desde la consola local.'
        }), 403

    nombre = str(data.get('nombre', '')).strip()
    if not nombre or len(nombre) > 100:
        return jsonify({'mensaje': 'Ingresa un nombre válido.'}), 400

    token = secrets.token_urlsafe(32)
    ahora = int(time.time())
    RegistroPendiente.query.filter(
        RegistroPendiente.expires_at <= ahora
    ).delete(synchronize_session=False)
    registro = RegistroPendiente.query.filter_by(email=username).first()
    if registro and registro.expires_at > ahora:
        if registro.usuario_id is not None:
            return jsonify({
                'mensaje': 'Ya hay un cambio de correo pendiente para esta dirección.'
            }), 409
        return jsonify({
            'mensaje': 'Ya enviamos un enlace a ese correo. Revisa tu bandeja de entrada.'
        }), 202
    if not registro:
        registro = RegistroPendiente(email=username)
        db.session.add(registro)
    registro.nombre = nombre
    registro.token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    registro.expires_at = ahora + REGISTRO_EXPIRA_SEGUNDOS
    db.session.commit()

    enlace = (
        f"{current_app.config['MOTOSMART_PUBLIC_URL']}/verificar-registro"
        f"#{quote(token, safe='')}"
    )
    if not enviar_correo(
        username,
        'Verifica tu correo para crear tu cuenta de MotoSmart',
        f'Hola {nombre},\n\n'
        'Para verificar que este correo te pertenece y terminar de crear tu cuenta, '
        'abre este enlace:\n\n'
        f'{enlace}\n\n'
        'El enlace vence en 30 minutos. Si no solicitaste esta cuenta, puedes ignorar este mensaje.'
    ):
        db.session.delete(registro)
        db.session.commit()
        return jsonify({
            'mensaje': 'No se pudo enviar el correo de verificación. Revisa la configuración SMTP e inténtalo de nuevo.'
        }), 503

    return jsonify({
        'mensaje': 'Te enviamos un enlace para verificar tu correo y terminar de crear tu cuenta.'
    }), 202


@auth_bp.route('/verificar-registro', methods=['GET'])
def pagina_verificar_registro():
    return render_template('verify_registration.html')


@auth_bp.route('/register/verify', methods=['POST'])
def verificar_registro():
    data = request.get_json(silent=True) or {}
    token = str(data.get('token', ''))
    password = str(data.get('password', ''))
    if len(password) < 6:
        return jsonify({'mensaje': 'La contraseña debe tener al menos 6 caracteres.'}), 400

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    ahora = int(time.time())
    registro = RegistroPendiente.query.filter_by(token_hash=token_hash).first()
    if not registro or registro.usuario_id is not None or registro.expires_at <= ahora:
        if registro:
            if registro.expires_at <= ahora:
                db.session.delete(registro)
                db.session.commit()
        return jsonify({'mensaje': 'El enlace no es válido o venció. Solicita uno nuevo.'}), 400
    if Usuario.query.filter_by(username=registro.email).first():
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'Ya existe una cuenta con ese correo.'}), 409

    nuevo_usuario = Usuario(username=registro.email, rol='cliente')
    nuevo_usuario.set_password(password)
    db.session.add(nuevo_usuario)
    cliente = Cliente.query.filter_by(email=registro.email).first()
    if cliente:
        cliente.nombre = registro.nombre
    else:
        cliente = Cliente(nombre=registro.nombre, email=registro.email)
        db.session.add(cliente)
    db.session.delete(registro)
    db.session.commit()
    return jsonify({
        'mensaje': 'Correo verificado y cuenta creada. Ya puedes iniciar sesión.'
    }), 201


@auth_bp.route('/mi-cuenta/verificar-email', methods=['POST'])
def verificar_cambio_correo():
    data = request.get_json(silent=True) or {}
    token = str(data.get('token', ''))
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    ahora = int(time.time())
    registro = RegistroPendiente.query.filter_by(token_hash=token_hash).first()
    if not registro or registro.usuario_id is None or registro.expires_at <= ahora:
        if registro and registro.expires_at <= ahora:
            db.session.delete(registro)
            db.session.commit()
        return jsonify({'mensaje': 'El enlace no es válido o venció. Solicita un nuevo cambio.'}), 400

    usuario = Usuario.query.get(registro.usuario_id)
    if not usuario:
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'La cuenta asociada ya no existe.'}), 404
    if Usuario.query.filter(
        Usuario.username == registro.email,
        Usuario.id != usuario.id
    ).first():
        db.session.delete(registro)
        db.session.commit()
        return jsonify({'mensaje': 'Ya existe una cuenta con ese correo.'}), 409

    cliente_actual = Cliente.query.filter_by(email=usuario.username).first()
    cliente_destino = Cliente.query.filter_by(email=registro.email).first()
    if cliente_actual and cliente_destino and cliente_actual.id != cliente_destino.id:
        Moto.query.filter_by(cliente_id=cliente_actual.id).update(
            {Moto.cliente_id: cliente_destino.id},
            synchronize_session=False
        )
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
    data = request.get_json()
    usuario = Usuario.query.filter_by(username=data['username']).first()
    if usuario and usuario.check_password(data['password']):
        # identity debe ser string
        token = create_access_token(
            identity=str(usuario.id),
            additional_claims={
                "rol": usuario.rol,
                "es_titular_taller": usuario.rol == 'mecanico' and not usuario.creado_por_id
            }
        )
        return jsonify({"mensaje": "Login exitoso", "token": token}), 200
    return jsonify({"mensaje": "Credenciales inválidas"}), 401


@auth_bp.route('/mi-cuenta', methods=['GET', 'PUT'])
@jwt_required()
def mi_cuenta():
    usuario = Usuario.query.get_or_404(get_jwt_identity())
    if request.method == 'GET':
        return jsonify({'email': usuario.username, 'rol': usuario.rol})

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
            Usuario.id != usuario.id
        ).first():
            return jsonify({'error': 'Ya existe una cuenta con ese correo.'}), 400

        ahora = int(time.time())
        RegistroPendiente.query.filter(
            RegistroPendiente.expires_at <= ahora
        ).delete(synchronize_session=False)
        registro = RegistroPendiente.query.filter_by(email=email).first()
        if registro:
            if registro.usuario_id == usuario.id and registro.expires_at > ahora:
                return jsonify({
                    'mensaje': 'Ya enviamos el enlace a la nueva dirección de correo.'
                }), 202
            return jsonify({
                'error': 'Ya hay una verificación pendiente para ese correo.'
            }), 409

        token = secrets.token_urlsafe(32)
        registro = RegistroPendiente(
            email=email,
            token_hash=hashlib.sha256(token.encode('utf-8')).hexdigest(),
            expires_at=ahora + REGISTRO_EXPIRA_SEGUNDOS,
            usuario_id=usuario.id
        )
        db.session.add(registro)
        db.session.commit()
        enlace = (
            f"{current_app.config['MOTOSMART_PUBLIC_URL']}/verificar-registro"
            f"#email={quote(token, safe='')}"
        )
        if not enviar_correo(
            email,
            'Confirma el cambio de correo de tu cuenta MotoSmart',
            'Para confirmar que controlas esta nueva dirección de correo, abre este enlace:\n\n'
            f'{enlace}\n\n'
            'El enlace vence en 30 minutos. Si no solicitaste este cambio, puedes ignorar este mensaje.'
        ):
            db.session.delete(registro)
            db.session.commit()
            return jsonify({
                'error': 'No se pudo enviar el correo de verificación. Revisa la configuración SMTP e inténtalo de nuevo.'
            }), 503
        return jsonify({
            'mensaje': 'Te enviamos un enlace para verificar la nueva dirección de correo.'
        }), 202

    if password and len(password) < 6:
        return jsonify({'error': 'La contraseña debe tener al menos 6 caracteres.'}), 400

    if password:
        usuario.set_password(password)
    db.session.commit()
    return jsonify({'mensaje': 'Datos de la cuenta actualizados.', 'email': usuario.username})
