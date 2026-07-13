from flask import Blueprint, request, jsonify
from db import db
from modelo.usuario import Usuario
from modelo.clientes import Cliente
from flask_jwt_extended import create_access_token

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if Usuario.query.filter_by(username=data['username']).first():
        return jsonify({"mensaje": "Usuario ya existe"}), 400

    rol = data.get('rol', 'cliente')
    if rol not in ('cliente', 'mecanico'):
        return jsonify({'mensaje': 'Rol no valido'}), 400

    nuevo_usuario = Usuario(username=data['username'], rol=rol)
    nuevo_usuario.set_password(data['password'])
    db.session.add(nuevo_usuario)
    if rol == 'cliente':
        cliente = Cliente.query.filter_by(email=data['username']).first()
        if cliente:
            cliente.nombre = data.get('nombre', cliente.nombre)
        else:
            db.session.add(Cliente(
                nombre=data.get('nombre', data['username']),
                email=data['username'],
                telefono=data.get('telefono')
            ))
    db.session.commit()
    return jsonify({"mensaje": "Usuario registrado con éxito"}), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    usuario = Usuario.query.filter_by(username=data['username']).first()
    if usuario and usuario.check_password(data['password']):
        # identity debe ser string
        token = create_access_token(
            identity=str(usuario.id),
            additional_claims={"rol": usuario.rol}
        )
        return jsonify({"mensaje": "Login exitoso", "token": token}), 200
    return jsonify({"mensaje": "Credenciales inválidas"}), 401
