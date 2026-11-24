from datetime import date

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy.orm import selectinload

from db import db
from modelo.citas import Cita
from modelo.clientes import Cliente
from modelo.moto import Moto
from services.paginacion import respuesta_paginada
from services.seguridad import registrar_auditoria
from services.tenencia import taller_actual_id, usuario_actual
from services.validacion import cuerpo_json, email, entero, telefono, texto


clientes_bp = Blueprint('clientes', __name__)


def _staff():
    return get_jwt().get('rol') in ('mecanico', 'admin')


def _serializar_cliente(cliente):
    return {'id': cliente.id, 'nombre': cliente.nombre, 'correo': cliente.email}


def _serializar_detalle(cliente, taller_id, citas_por_moto):
    return {
        'id': cliente.id,
        'nombre': cliente.nombre,
        'email': cliente.email,
        'telefono': cliente.telefono,
        'motos': [
            {
                'id': moto.id,
                'placa': moto.placa,
                'marca': moto.marca,
                'modelo': moto.modelo,
                'citas': [
                    {
                        'id': cita.id,
                        'fecha': cita.fecha.isoformat(),
                        'descripcion': cita.descripcion,
                    }
                    for cita in citas_por_moto.get(moto.id, ())
                ],
            }
            for moto in cliente.motos
            if moto.taller_id == taller_id and not moto.transferida
        ],
    }


def _preparar_detalle(clientes, taller_id):
    """Carga solo las citas próximas de las motos listadas."""
    motos = [
        moto
        for cliente in clientes
        for moto in cliente.motos
        if moto.taller_id == taller_id and not moto.transferida
    ]
    citas_por_moto = {}
    if motos:
        citas = (
            Cita.query
            .filter(
                Cita.taller_id == taller_id,
                Cita.fecha >= date.today(),
                Cita.moto_id.in_([moto.id for moto in motos]),
            )
            .order_by(Cita.fecha.asc(), Cita.id.asc())
            .all()
        )
        for cita in citas:
            citas_por_moto.setdefault(cita.moto_id, []).append(cita)
    return lambda cliente: _serializar_detalle(cliente, taller_id, citas_por_moto)


@clientes_bp.route('/clientes', methods=['POST'])
@jwt_required()
def crear_cliente():
    if not _staff():
        return jsonify({'error': 'No tienes permisos para crear clientes'}), 403
    taller_id = taller_actual_id()
    if not taller_id:
        return jsonify({'error': 'No se encontró el taller de la cuenta.'}), 404
    data = cuerpo_json()
    nombre = texto(data, 'nombre', maximo=100)
    correo = email(data, 'email')
    tel = telefono(data, 'telefono', requerido=False)
    if Cliente.query.filter_by(taller_id=taller_id, email=correo).first():
        return jsonify({'error': 'Ya existe un cliente con ese correo en el taller.'}), 409
    nuevo_cliente = Cliente(
        nombre=nombre,
        email=correo,
        telefono=tel,
        taller_id=taller_id,
    )
    db.session.add(nuevo_cliente)
    db.session.flush()
    registrar_auditoria('cliente', nuevo_cliente.id, 'crear', despues={
        'nombre': nombre, 'email': correo,
    })
    db.session.commit()
    return jsonify({'mensaje': 'Cliente creado con éxito', 'id': nuevo_cliente.id}), 201


@clientes_bp.route('/clientes', methods=['GET'])
@jwt_required()
def listar_clientes():
    if not _staff():
        return jsonify({'error': 'No tienes permisos para consultar los clientes'}), 403
    clientes = Cliente.query.filter_by(
        taller_id=taller_actual_id()
    ).order_by(Cliente.nombre.asc(), Cliente.id.asc())
    return respuesta_paginada(clientes, _serializar_cliente)


@clientes_bp.route('/clientes/detalle', methods=['GET'])
@jwt_required()
def listar_clientes_detalle():
    if not _staff():
        return jsonify({'error': 'No tienes permisos para consultar los clientes'}), 403
    taller_id = taller_actual_id()
    clientes = (
        Cliente.query
        .filter_by(taller_id=taller_id)
        .options(selectinload(Cliente.motos))
        .order_by(Cliente.nombre.asc(), Cliente.id.asc())
    )
    return respuesta_paginada(
        clientes,
        _serializar_cliente,
        preparar=lambda items: _preparar_detalle(items, taller_id),
    )


@clientes_bp.route('/clientes/<int:id>', methods=['GET'])
@jwt_required()
def obtener_cliente(id):
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    if get_jwt().get('rol') == 'cliente':
        cliente = Cliente.query.filter_by(
            email=usuario.username, taller_id=usuario.taller_id
        ).first()
        if not cliente or cliente.id != id:
            return jsonify({'error': 'No puedes consultar el perfil de otro cliente.'}), 403
    elif _staff():
        cliente = Cliente.query.filter_by(id=id, taller_id=taller_actual_id()).first()
    else:
        return jsonify({'error': 'No tienes permisos para consultar clientes'}), 403
    if not cliente:
        return jsonify({'error': 'Cliente no encontrado.'}), 404
    return jsonify(_serializar_cliente(cliente)), 200


@clientes_bp.route('/clientes/<int:id>', methods=['PUT', 'PATCH'])
@jwt_required()
def actualizar_cliente(id):
    claims = get_jwt()
    rol = claims.get('rol')
    usuario = usuario_actual()
    if rol == 'cliente':
        if not usuario:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        cliente = Cliente.query.filter_by(
            email=usuario.username, taller_id=usuario.taller_id
        ).first()
        if not cliente:
            return jsonify({'error': 'No se encontró tu perfil de cliente.'}), 404
        if cliente.id != id:
            return jsonify({'error': 'No puedes modificar el perfil de otro cliente.'}), 403
    elif _staff():
        cliente = Cliente.query.filter_by(
            id=id, taller_id=taller_actual_id()
        ).first()
        if not cliente:
            return jsonify({'error': 'Cliente no encontrado.'}), 404
    else:
        return jsonify({'error': 'No tienes permisos para actualizar este cliente'}), 403

    data = cuerpo_json()
    antes = {'nombre': cliente.nombre, 'telefono': cliente.telefono}
    if 'nombre' in data:
        cliente.nombre = texto(data, 'nombre', maximo=100)
    if 'telefono' in data:
        cliente.telefono = telefono(data, 'telefono', requerido=False)
    if 'email' in data and data.get('email'):
        return jsonify({'error': 'El correo se cambia desde Ajustes de cuenta con verificación.'}), 400

    registrar_auditoria('cliente', cliente.id, 'actualizar', antes=antes, despues={
        'nombre': cliente.nombre, 'telefono': cliente.telefono,
    })
    db.session.commit()
    return jsonify({'mensaje': 'Cliente actualizado con éxito'}), 200


@clientes_bp.route('/clientes/<int:id>', methods=['DELETE'])
@jwt_required()
def borrar_cliente(id):
    if not _staff():
        return jsonify({'error': 'No tienes permisos para eliminar clientes'}), 403
    cliente = Cliente.query.filter_by(
        id=id, taller_id=taller_actual_id()
    ).first()
    if not cliente:
        return jsonify({'error': 'Cliente no encontrado.'}), 404
    if Moto.query.filter_by(cliente_id=cliente.id).first():
        return jsonify({
            'error': 'No se puede eliminar el cliente porque tiene motos registradas. '
                     'Transfiere o elimina primero sus motos.'
        }), 409
    antes = {'nombre': cliente.nombre, 'email': cliente.email}
    registrar_auditoria('cliente', cliente.id, 'eliminar', antes=antes)
    db.session.delete(cliente)
    db.session.commit()
    return jsonify({'mensaje': 'Cliente eliminado con éxito'}), 200
