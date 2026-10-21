from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from db import db
from modelo.usuario import Usuario

mecanicos_bp = Blueprint('mecanicos', __name__)


def taller_actual():
    """El personal no puede crear ni borrar los accesos de otros mecánicos."""
    if get_jwt().get('rol') != 'mecanico':
        return None
    usuario = Usuario.query.get(get_jwt_identity())
    if not usuario or usuario.creado_por_id:
        return None
    return usuario


def serializar(mecanico):
    return {'id': mecanico.id, 'email': mecanico.username}


@mecanicos_bp.route('/mecanicos', methods=['GET'])
@jwt_required()
def listar_mecanicos():
    titular = taller_actual()
    if not titular:
        return jsonify({'error': 'Solo el titular del taller puede administrar mecánicos.'}), 403
    mecanicos = Usuario.query.filter_by(rol='mecanico', creado_por_id=titular.id).order_by(Usuario.username.asc()).all()
    return jsonify([serializar(mecanico) for mecanico in mecanicos])


@mecanicos_bp.route('/mecanicos', methods=['POST'])
@jwt_required()
def crear_mecanico():
    titular = taller_actual()
    if not titular:
        return jsonify({'error': 'Solo el titular del taller puede crear mecánicos.'}), 403
    data = request.get_json(silent=True) or {}
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    if not email or '@' not in email or len(email) > 50:
        return jsonify({'error': 'Ingresa un correo electrónico válido.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'La contraseña debe tener al menos 6 caracteres.'}), 400
    if Usuario.query.filter_by(username=email).first():
        return jsonify({'error': 'Ya existe una cuenta con ese correo.'}), 400
    mecanico = Usuario(username=email, rol='mecanico', creado_por_id=titular.id)
    mecanico.set_password(password)
    db.session.add(mecanico)
    db.session.commit()
    return jsonify({'mensaje': 'Mecánico agregado al taller.', 'mecanico': serializar(mecanico)}), 201


@mecanicos_bp.route('/mecanicos/<int:mecanico_id>', methods=['DELETE'])
@jwt_required()
def eliminar_mecanico(mecanico_id):
    titular = taller_actual()
    if not titular:
        return jsonify({'error': 'Solo el titular del taller puede administrar mecánicos.'}), 403
    mecanico = Usuario.query.filter_by(id=mecanico_id, rol='mecanico', creado_por_id=titular.id).first_or_404()
    db.session.delete(mecanico)
    db.session.commit()
    return jsonify({'mensaje': 'Acceso del mecánico eliminado.'})
