from flask import Blueprint, request, jsonify
from db import db
from modelo.clientes import Cliente
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from roles import rol_required

clientes_bp = Blueprint('clientes', __name__)

@clientes_bp.route('/clientes', methods=['POST'])

def crear_cliente():
    data = request.get_json()
    nuevo_cliente = Cliente(
        nombre=data['nombre'],
        email=data['email'],
        telefono=data.get('telefono')
    )
    db.session.add(nuevo_cliente)
    db.session.commit()
    return jsonify({"mensaje": "Cliente creado con éxito", "id": nuevo_cliente.id}), 201

@clientes_bp.route('/clientes', methods=['GET'])
@rol_required("admin")
def listar_clientes():
    clientes = Cliente.query.all()

    resultado = []
    for c in clientes:
        resultado.append({
            "id": c.id,
            "nombre": c.nombre,
            "correo": c.correo
        })

    return jsonify(resultado), 200


@clientes_bp.route('/clientes/<int:id>', methods=['PUT'])
@jwt_required()
def actualizar_cliente(id):    
    # Un cliente solo puede actualizar su propio perfil, un admin puede actualizar cualquiera.
    claims = get_jwt()
    rol = claims.get("rol")
    usuario_id = int(get_jwt_identity())

    if rol != 'admin' and usuario_id != id:
        return jsonify({"error": "No tienes permisos para actualizar este cliente"}), 403

    data = request.get_json()
    cliente = Cliente.query.get_or_404(id)

    cliente.nombre = data.get('nombre', cliente.nombre)
    cliente.correo = data.get('correo', cliente.correo) # Corregido para usar 'correo' consistentemente
    cliente.telefono = data.get('telefono', cliente.telefono)

    db.session.commit()
    return jsonify({"mensaje": "Cliente actualizado con éxito"})



@clientes_bp.route('/clientes/detalle', methods=['GET'])
@jwt_required()
def listar_clientes_detalle():
    if get_jwt().get('rol') not in ('admin', 'mecanico'):
        return jsonify({"error": "No tienes permisos para consultar los clientes"}), 403

    clientes = Cliente.query.all()
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
                        } for c in m.citas
                    ]
                } for m in cl.motos
            ]
        })
    return jsonify(resultado)

@clientes_bp.route('/clientes/<int:id>', methods=['DELETE'])
@rol_required("admin")
def borrar_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    db.session.delete(cliente)
    db.session.commit()
    return jsonify({"mensaje": "Cliente eliminado con éxito"}), 200
