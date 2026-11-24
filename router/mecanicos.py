from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from db import db
from modelo.clientes import Cliente
from modelo.registro_pendiente import RegistroPendiente
from modelo.usuario import Usuario
from services.seguridad import limitar, registrar_auditoria
from services.tenencia import es_titular, usuario_actual
from services.validacion import cuerpo_json, email_valor, password as validar_password


mecanicos_bp = Blueprint('mecanicos', __name__)


def taller_actual():
    """El personal no puede crear ni borrar los accesos de otros mecánicos."""
    usuario = usuario_actual()
    if not es_titular(usuario):
        return None
    return usuario


def serializar(mecanico):
    return {
        'id': mecanico.id,
        'email': mecanico.username,
        'email_verificado': bool(mecanico.email_verificado),
    }


@mecanicos_bp.route('/mecanicos', methods=['GET'])
@jwt_required()
def listar_mecanicos():
    titular = taller_actual()
    if not titular:
        return jsonify({'error': 'Solo el titular del taller puede administrar mecánicos.'}), 403
    mecanicos = Usuario.query.filter_by(
        rol='mecanico',
        creado_por_id=titular.id,
        taller_id=titular.taller_id,
    ).order_by(Usuario.username.asc()).all()
    return jsonify([serializar(mecanico) for mecanico in mecanicos])


@mecanicos_bp.route('/mecanicos', methods=['POST'])
@jwt_required()
@limitar(20, 3600, por='usuario', nombre='crear_mecanico')
def crear_mecanico():
    titular = taller_actual()
    if not titular:
        return jsonify({'error': 'Solo el titular del taller puede crear mecánicos.'}), 403
    data = cuerpo_json()
    email = email_valor(data.get('email'))

    if Usuario.query.filter_by(username=email).first():
        return jsonify({'error': 'Ya existe una cuenta con ese correo.'}), 409
    if Cliente.query.filter_by(email=email).first():
        return jsonify({
            'error': 'Ese correo pertenece a un cliente. Pídele que cree su cuenta y luego '
                     'asígnale permisos desde su propio registro.'
        }), 409
    if RegistroPendiente.query.filter_by(email=email).first():
        return jsonify({'error': 'Ese correo tiene una verificación pendiente.'}), 409

    if current_app.config.get('MOTOSMART_REQUIRE_EMAIL_VERIFICATION'):
        from router.auth import crear_verificacion
        _, error = crear_verificacion(
            email,
            'Invitación para unirte al equipo de MotoSmart',
            f'El taller {titular.nombre or titular.username} te invitó a unirte como mecánico. '
            'Abre el enlace y define tu propia contraseña.',
            'mecanico',
            titular.taller_id,
            usuario_id=titular.id,
            nombre=email.split('@')[0],
        )
        if error:
            return jsonify({'error': error}), 503
        return jsonify({
            'mensaje': 'Invitación enviada. El mecánico debe confirmar su correo y crear su contraseña.',
            'invitacion_pendiente': True,
        }), 202

    clave = validar_password(data.get('password'))
    mecanico = Usuario(
        username=email,
        rol='mecanico',
        nombre=email.split('@')[0],
        taller_id=titular.taller_id,
        creado_por_id=titular.id,
        email_verificado=True,
    )
    mecanico.set_password(clave)
    db.session.add(mecanico)
    try:
        db.session.flush()
        registrar_auditoria('usuario', mecanico.id, 'crear_mecanico', despues={
            'email': mecanico.username,
        })
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Ya existe una cuenta con ese correo.'}), 409
    return jsonify({
        'mensaje': 'Mecánico agregado al taller.',
        'mecanico': serializar(mecanico),
    }), 201


@mecanicos_bp.route('/mecanicos/<int:mecanico_id>', methods=['DELETE'])
@jwt_required()
def eliminar_mecanico(mecanico_id):
    titular = taller_actual()
    if not titular:
        return jsonify({'error': 'Solo el titular del taller puede administrar mecánicos.'}), 403
    mecanico = Usuario.query.filter_by(
        id=mecanico_id,
        rol='mecanico',
        creado_por_id=titular.id,
        taller_id=titular.taller_id,
    ).first()
    if not mecanico:
        return jsonify({'error': 'Mecánico no encontrado.'}), 404
    registrar_auditoria('usuario', mecanico.id, 'eliminar_mecanico', antes={
        'email': mecanico.username,
    })
    db.session.delete(mecanico)
    db.session.commit()
    return jsonify({'mensaje': 'Acceso del mecánico eliminado. Sus tokens quedaron revocados.'})
