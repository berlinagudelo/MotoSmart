from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from db import db
from modelo.citas import Cita
from modelo.clientes import Cliente
from modelo.moto import Moto
from modelo.usuario import Usuario

citas_bp = Blueprint('citas', __name__)


def mecanico_requerido():
    return get_jwt().get('rol') == 'mecanico'


def cliente_actual(crear=False):
    usuario = Usuario.query.get(int(get_jwt_identity()))
    if not usuario:
        return None
    cliente = Cliente.query.filter_by(email=usuario.username).first()
    if not cliente and crear:
        cliente = Cliente(nombre=usuario.username.split('@')[0], email=usuario.username)
        db.session.add(cliente)
        db.session.flush()
    return cliente


def serializar_cita(cita):
    moto = cita.moto
    return {
        'id': cita.id,
        'fecha': cita.fecha.isoformat(),
        'descripcion': cita.descripcion or '',
        'moto': {
            'id': moto.id,
            'placa': moto.placa,
            'marca': moto.marca,
            'modelo': moto.modelo,
            'cliente': moto.cliente.nombre if moto.cliente else None
        } if moto else None
    }


@citas_bp.route('/citas', methods=['POST'])
@jwt_required()
def crear_cita():
    if get_jwt().get('rol') != 'cliente':
        return jsonify({'error': 'Solo clientes pueden agendar citas'}), 403

    data = request.get_json()
    cliente = cliente_actual(crear=True)
    moto = Moto.query.filter_by(id=data.get('moto_id'), cliente_id=cliente.id).first() if cliente else None
    if not moto:
        return jsonify({'error': 'La moto seleccionada no existe'}), 404
    try:
        fecha = datetime.strptime(data['fecha'], '%Y-%m-%d').date()
    except (KeyError, ValueError):
        return jsonify({'error': 'La fecha no es valida'}), 400

    cita = Cita(fecha=fecha, descripcion=data.get('descripcion', '').strip(), moto_id=moto.id)
    db.session.add(cita)
    db.session.commit()
    return jsonify({'mensaje': 'Cita agendada con exito', 'cita': serializar_cita(cita)}), 201


@citas_bp.route('/citas/detalle', methods=['GET'])
@jwt_required()
def listar_citas_detalle():
    if not mecanico_requerido():
        return jsonify({'error': 'Solo mecanicos pueden ver las citas'}), 403
    return jsonify([serializar_cita(cita) for cita in Cita.query.order_by(Cita.fecha.asc()).all()])


@citas_bp.route('/mis_citas', methods=['GET'])
@jwt_required()
def listar_mis_citas():
    if get_jwt().get('rol') != 'cliente':
        return jsonify({'error': 'Esta vista es solo para clientes'}), 403
    cliente = cliente_actual()
    if not cliente:
        return jsonify([])
    citas = Cita.query.join(Moto).filter(Moto.cliente_id == cliente.id).order_by(Cita.fecha.asc()).all()
    return jsonify([serializar_cita(cita) for cita in citas])


@citas_bp.route('/citas/<int:id>', methods=['PUT'])
@jwt_required()
def actualizar_cita(id):
    if not mecanico_requerido():
        return jsonify({'error': 'Solo mecanicos pueden editar citas'}), 403

    cita = Cita.query.get_or_404(id)
    data = request.get_json()
    if 'fecha' in data:
        try:
            cita.fecha = datetime.strptime(data['fecha'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'La fecha no es valida'}), 400
    if 'moto_id' in data:
        moto = Moto.query.get(data['moto_id'])
        if not moto:
            return jsonify({'error': 'La moto seleccionada no existe'}), 404
        cita.moto_id = moto.id
    cita.descripcion = data.get('descripcion', cita.descripcion)
    db.session.commit()
    return jsonify({'mensaje': 'Cita actualizada con exito', 'cita': serializar_cita(cita)})


@citas_bp.route('/citas/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_cita(id):
    if not mecanico_requerido():
        return jsonify({'error': 'Solo mecanicos pueden eliminar citas'}), 403
    cita = Cita.query.get_or_404(id)
    db.session.delete(cita)
    db.session.commit()
    return jsonify({'mensaje': 'Cita eliminada con exito'})
