from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from sqlalchemy.exc import IntegrityError

from db import db
from modelo.clientes import Cliente
from modelo.moto import Moto
from modelo.usuario import Usuario
from roles import rol_required

motos_bp = Blueprint('motos', __name__)
TIPOS_TECNOLOGIA = ('electronica', 'no_electronica')


def serializar_moto(moto, incluir_cliente=False):
    ordenes = sorted(
        moto.ordenes_servicio,
        key=lambda orden: orden.actualizada_en or orden.creada_en,
        reverse=True
    )
    ultima_orden = ordenes[0] if ordenes else None
    resultado = {
        'id': moto.id,
        'placa': moto.placa,
        'marca': moto.marca,
        'modelo': moto.modelo,
        'tipo_tecnologia': moto.tipo_tecnologia or 'electronica',
        'trabajo_actual': {
            'numero': ultima_orden.numero,
            'estado': ultima_orden.estado,
            'descripcion': ultima_orden.descripcion,
            'actualizada_en': ultima_orden.actualizada_en.isoformat()
        } if ultima_orden else None
    }
    if incluir_cliente:
        resultado['cliente'] = {
            'id': moto.cliente.id,
            'nombre': moto.cliente.nombre,
            'email': moto.cliente.email,
            'telefono': moto.cliente.telefono
        } if moto.cliente else None
    return resultado


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

    tipo_tecnologia = data.get('tipo_tecnologia', 'electronica').strip().lower()
    if tipo_tecnologia not in TIPOS_TECNOLOGIA:
        return jsonify({'error': 'Selecciona un tipo de moto valido'}), 400

    nueva_moto = Moto(
        placa=placa,
        marca=data['marca'],
        modelo=data['modelo'],
        tipo_tecnologia=tipo_tecnologia,
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

    return jsonify([serializar_moto(m) for m in motos])


@motos_bp.route('/motos/detalle', methods=['GET'])
@jwt_required()
def listar_motos_detalle():
    if get_jwt().get('rol') not in ('mecanico', 'admin'):
        return jsonify({'error': 'No tienes permisos para esta accion'}), 403

    motos = Moto.query.all()
    return jsonify([serializar_moto(m, incluir_cliente=True) for m in motos])


@motos_bp.route('/motos/<int:id>', methods=['DELETE'])
@jwt_required()
def borrar_moto(id):
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecanicos pueden eliminar motos'}), 403
    moto = Moto.query.get_or_404(id)
    db.session.delete(moto)
    db.session.commit()
    return jsonify({'mensaje': 'Moto eliminada con exito'}), 200
