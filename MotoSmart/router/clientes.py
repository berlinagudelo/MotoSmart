from flask import Blueprint, request, jsonify
from db import db
from modelo.clientes import Cliente
from flask_jwt_extended import jwt_required, get_jwt
from services.tenencia import taller_actual_id, usuario_actual

clientes_bp = Blueprint('clientes', __name__)

@clientes_bp.route('/clientes', methods=['POST'])
@jwt_required()
def crear_cliente():
    if get_jwt().get('rol') not in ('mecanico', 'admin'):
        return jsonify({"error": "No tienes permisos para crear clientes"}), 403
    data = request.get_json(silent=True) or {}
    taller_id = taller_actual_id()
    if not taller_id:
        return jsonify({"error": "No se encontró el taller de la cuenta."}), 404
    nuevo_cliente = Cliente(
        nombre=data.get('nombre', '').strip(),
        email=data.get('email', '').strip().lower(),
        telefono=data.get('telefono'),
        taller_id=taller_id,
    )
    db.session.add(nuevo_cliente)
    db.session.commit()
    return jsonify({"mensaje": "Cliente creado con éxito", "id": nuevo_cliente.id}), 201

@clientes_bp.route('/clientes', methods=['GET'])
@jwt_required()
def listar_clientes():
    if get_jwt().get('rol') not in ('admin', 'mecanico'):
        return jsonify({"error": "No tienes permisos para consultar los clientes"}), 403
    clientes = Cliente.query.filter_by(taller_id=taller_actual_id()).all()

    resultado = []
    for c in clientes:
        resultado.append({
            "id": c.id,
            "nombre": c.nombre,
            "correo": c.email
        })

    return jsonify(resultado), 200


@clientes_bp.route('/clientes/<int:id>', methods=['PUT'])
@jwt_required()
def actualizar_cliente(id):
    # Un cliente solo puede actualizar su propio perfil, un admin puede actualizar cualquiera.
    claims = get_jwt()
    rol = claims.get("rol")
    usuario = usuario_actual()
    if rol != 'admin' and (not usuario or usuario.rol != 'cliente'):
        return jsonify({"error": "No tienes permisos para actualizar este cliente"}), 403
    if rol == 'cliente':
        cliente = Cliente.query.filter_by(
            email=usuario.username, taller_id=usuario.taller_id
        ).first_or_404()
    else:
        cliente = Cliente.query.filter_by(
            id=id, taller_id=taller_actual_id()
        ).first_or_404()
    data = request.get_json(silent=True) or {}

    cliente.nombre = data.get('nombre', cliente.nombre)
    cliente.telefono = data.get('telefono', cliente.telefono)

    db.session.commit()
    return jsonify({"mensaje": "Cliente actualizado con éxito"})



@clientes_bp.route('/clientes/detalle', methods=['GET'])
@jwt_required()
def listar_clientes_detalle():
    if get_jwt().get('rol') not in ('admin', 'mecanico'):
        return jsonify({"error": "No tienes permisos para consultar los clientes"}), 403

    clientes = Cliente.query.filter_by(taller_id=taller_actual_id()).all()
    resultado = []
    for cl in clientes:
        resultado.append({
            "id": cl.id,
            "nombre": cl.nombre,
            "email": cl.email,
            "telefono": cl.telefono,
            "motos": [
                {
                    "id": m.id,
                    "placa": m.placa,
                    "marca": m.marca,
                    "modelo": m.modelo,
                    "citas": [
                        {
                            "id": c.id,
                            "fecha": str(c.fecha),
                            "descripcion": c.descripcion
                        } for c in m.citas if c.taller_id == taller_actual_id()
                    ]
                } for m in cl.motos
                if m.taller_id == taller_actual_id() and not m.transferida
            ]
        })
    return jsonify(resultado)

@clientes_bp.route('/clientes/<int:id>', methods=['DELETE'])
@jwt_required()
def borrar_cliente(id):
    if get_jwt().get('rol') not in ('admin', 'mecanico'):
        return jsonify({"error": "No tienes permisos para eliminar clientes"}), 403
    cliente = Cliente.query.filter_by(
        id=id, taller_id=taller_actual_id()
    ).first_or_404()
    db.session.delete(cliente)
    db.session.commit()
    return jsonify({"mensaje": "Cliente eliminado con éxito"}), 200
