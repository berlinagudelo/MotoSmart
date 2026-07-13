from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from sqlalchemy.exc import IntegrityError

from db import db
from modelo.clientes import Cliente
from modelo.moto import Moto
from modelo.usuario import Usuario
from roles import rol_required

motos_bp = Blueprint('motos', __name__)


@motos_bp.route('/motos', methods=['POST'])
@jwt_required()
def crear_moto():
    rol = get_jwt().get('rol')
    if rol not in ('cliente', 'mecanico'):
        return jsonify({'error': 'No tienes permisos para registrar motos'}), 403

    data = request.get_json()
    placa = data['placa'].strip().upper()
    if Moto.query.filter_by(placa=placa).first():
        return jsonify({'error': 'Ya existe una moto con esa placa'}), 400

    if rol == 'cliente':
        usuario = Usuario.query.get(int(get_jwt_identity()))
        cliente = Cliente.query.filter_by(email=usuario.username).first() if usuario else None
        if not cliente and usuario:
            cliente = Cliente(nombre=usuario.username.split('@')[0], email=usuario.username)
            db.session.add(cliente)
            db.session.flush()
        if not cliente:
            return jsonify({'error': 'No fue posible identificar el cliente'}), 400
    else:
        correo_cliente = data.get('cliente_email', '').strip().lower()
        if not correo_cliente:
            return jsonify({'error': 'Ingresa el correo del cliente'}), 400
        cliente = Cliente.query.filter_by(email=correo_cliente).first()
        if not cliente:
            cliente = Cliente(
                nombre=data.get('cliente_nombre', '').strip() or correo_cliente.split('@')[0],
                email=correo_cliente
            )
            db.session.add(cliente)
            db.session.flush()

    nueva_moto = Moto(
        placa=placa,
        marca=data['marca'],
        modelo=data['modelo'],
        cliente_id=cliente.id
    )
    db.session.add(nueva_moto)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'No fue posible registrar la moto'}), 400
    return jsonify({'mensaje': 'Moto creada con exito', 'id': nueva_moto.id}), 201


@motos_bp.route('/motos', methods=['GET'])
@jwt_required()
def listar_motos():
    usuario = Usuario.query.get(int(get_jwt_identity()))
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    if get_jwt().get('rol') in ('mecanico', 'admin'):
        motos = Moto.query.all()
    else:
        cliente = Cliente.query.filter_by(email=usuario.username).first()
        motos = Moto.query.filter_by(cliente_id=cliente.id).all() if cliente else []

    return jsonify([
        {'id': m.id, 'placa': m.placa, 'marca': m.marca, 'modelo': m.modelo}
        for m in motos
    ])


@motos_bp.route('/motos/detalle', methods=['GET'])
@jwt_required()
def listar_motos_detalle():
    if get_jwt().get('rol') not in ('mecanico', 'admin'):
        return jsonify({'error': 'No tienes permisos para esta accion'}), 403

    motos = Moto.query.all()
    return jsonify([
        {
            'id': m.id,
            'placa': m.placa,
            'marca': m.marca,
            'modelo': m.modelo,
            'cliente': {
                'id': m.cliente.id,
                'nombre': m.cliente.nombre,
                'email': m.cliente.email,
                'telefono': m.cliente.telefono
            } if m.cliente else None
        }
        for m in motos
    ])


@motos_bp.route('/motos/<int:id>', methods=['DELETE'])
@jwt_required()
def borrar_moto(id):
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecanicos pueden eliminar motos'}), 403
    moto = Moto.query.get_or_404(id)
    db.session.delete(moto)
    db.session.commit()
    return jsonify({'mensaje': 'Moto eliminada con exito'}), 200
