from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy import false
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from db import db
from modelo.citas import Cita
from modelo.clientes import Cliente
from modelo.diagnostico import Diagnostico
from modelo.factura import Factura
from modelo.moto import Moto
from modelo.orden_servicio import OrdenServicio
from services.consultas import ultimas_ordenes_por_moto
from services.paginacion import respuesta_paginada
from services.seguridad import registrar_auditoria
from services.tenencia import taller_actual_id, usuario_actual
from services.validacion import cuerpo_json, email, placa, texto


motos_bp = Blueprint('motos', __name__)
TIPOS_TECNOLOGIA = ('electronica', 'no_electronica')


_SIN_CALCULAR = object()


def serializar_moto(moto, incluir_cliente=False, ultima_orden=_SIN_CALCULAR):
    if ultima_orden is _SIN_CALCULAR:
        taller_id = taller_actual_id()
        ultima_orden = max(
            (
                orden for orden in moto.ordenes_servicio
                if orden.taller_id == taller_id
            ),
            key=lambda orden: (
                orden.actualizada_en or orden.creada_en, orden.id,
            ),
            default=None,
        )
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
            'actualizada_en': ultima_orden.actualizada_en.isoformat(),
        } if ultima_orden else None,
    }
    if incluir_cliente:
        resultado['cliente'] = {
            'id': moto.cliente.id,
            'nombre': moto.cliente.nombre,
            'email': moto.cliente.email,
            'telefono': moto.cliente.telefono,
        } if moto.cliente else None
    return resultado


@motos_bp.route('/motos', methods=['POST'])
@jwt_required()
def crear_moto():
    rol = get_jwt().get('rol')
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    taller_id = usuario.taller_id
    if rol not in ('cliente', 'mecanico'):
        return jsonify({'error': 'No tienes permisos para registrar motos'}), 403

    data = cuerpo_json()
    numero_placa = placa(data, 'placa')
    marca = texto(data, 'marca', maximo=50)
    modelo = texto(data, 'modelo', maximo=50)
    tipo_tecnologia = texto(
        data, 'tipo_tecnologia', requerido=False, default='electronica',
        lower=True, maximo=20,
    )
    if tipo_tecnologia not in TIPOS_TECNOLOGIA:
        return jsonify({'error': 'Selecciona un tipo de moto válido'}), 400

    if Moto.query.filter_by(
        placa=numero_placa, taller_id=taller_id, transferida=False
    ).first():
        return jsonify({'error': 'Ya existe una moto con esa placa'}), 409

    if rol == 'cliente':
        cliente = Cliente.query.filter_by(
            email=usuario.username, taller_id=taller_id
        ).first()
        if not cliente:
            cliente = Cliente(
                nombre=usuario.nombre or usuario.username.split('@')[0],
                email=usuario.username,
                taller_id=taller_id,
            )
            db.session.add(cliente)
            db.session.flush()
    else:
        correo_cliente = email(data, 'cliente_email')
        nombre_cliente = texto(
            data, 'cliente_nombre', requerido=False, default=None, maximo=100
        )
        cliente = Cliente.query.filter_by(
            email=correo_cliente, taller_id=taller_id
        ).first()
        if not cliente:
            cliente = Cliente(
                nombre=nombre_cliente or correo_cliente.split('@')[0],
                email=correo_cliente,
                taller_id=taller_id,
            )
            db.session.add(cliente)
            db.session.flush()

    nueva_moto = Moto(
        placa=numero_placa,
        marca=marca,
        modelo=modelo,
        tipo_tecnologia=tipo_tecnologia,
        cliente_id=cliente.id,
        taller_id=taller_id,
    )
    db.session.add(nueva_moto)
    try:
        db.session.flush()
        registrar_auditoria('moto', nueva_moto.id, 'crear', despues={
            'placa': nueva_moto.placa,
            'marca': nueva_moto.marca,
            'modelo': nueva_moto.modelo,
        })
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'No fue posible registrar la moto. Verifica la placa.'}), 409
    return jsonify({'mensaje': 'Moto creada con éxito', 'id': nueva_moto.id}), 201


def _serializador_motos(motos, incluir_cliente=False):
    ultimas = ultimas_ordenes_por_moto(
        (moto.id for moto in motos), taller_actual_id()
    )
    return lambda moto: serializar_moto(
        moto, incluir_cliente=incluir_cliente, ultima_orden=ultimas.get(moto.id)
    )


def _consulta_motos(usuario):
    consulta = Moto.query.options(joinedload(Moto.cliente))
    if get_jwt().get('rol') in ('mecanico', 'admin'):
        return consulta.filter_by(taller_id=usuario.taller_id, transferida=False)
    cliente = Cliente.query.filter_by(
        email=usuario.username, taller_id=usuario.taller_id
    ).first()
    if not cliente:
        return consulta.filter(false())
    return consulta.filter_by(
        cliente_id=cliente.id, taller_id=usuario.taller_id, transferida=False
    )


@motos_bp.route('/motos', methods=['GET'])
@jwt_required()
def listar_motos():
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    consulta = _consulta_motos(usuario).order_by(Moto.id.asc())
    return respuesta_paginada(
        consulta, serializar_moto,
        preparar=lambda items: _serializador_motos(items),
    )


@motos_bp.route('/motos/detalle', methods=['GET'])
@jwt_required()
def listar_motos_detalle():
    if get_jwt().get('rol') not in ('mecanico', 'admin'):
        return jsonify({'error': 'No tienes permisos para esta acción'}), 403
    consulta = (
        Moto.query
        .filter_by(taller_id=taller_actual_id(), transferida=False)
        .options(joinedload(Moto.cliente))
        .order_by(Moto.id.asc())
    )
    return respuesta_paginada(
        consulta,
        serializar_moto,
        preparar=lambda items: _serializador_motos(items, incluir_cliente=True),
    )


@motos_bp.route('/motos/<int:id>', methods=['GET'])
@jwt_required()
def obtener_moto(id):
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    moto = Moto.query.filter_by(
        id=id, taller_id=usuario.taller_id, transferida=False
    ).first()
    if not moto:
        return jsonify({'error': 'Moto no encontrada.'}), 404
    if get_jwt().get('rol') == 'cliente':
        cliente = Cliente.query.filter_by(
            email=usuario.username, taller_id=usuario.taller_id
        ).first()
        if not cliente or moto.cliente_id != cliente.id:
            return jsonify({'error': 'No puedes consultar una moto de otro cliente.'}), 403
    return jsonify(serializar_moto(
        moto,
        incluir_cliente=True,
        ultima_orden=ultimas_ordenes_por_moto(
            [moto.id], usuario.taller_id
        ).get(moto.id),
    )), 200


@motos_bp.route('/motos/<int:id>', methods=['DELETE'])
@jwt_required()
def borrar_moto(id):
    rol = get_jwt().get('rol')
    personal = rol in ('mecanico', 'admin')
    moto = Moto.query.filter_by(
        id=id, taller_id=taller_actual_id(), transferida=False
    ).first()
    if not moto:
        return jsonify({'error': 'Moto no encontrada.'}), 404
    if not personal:
        usuario = usuario_actual()
        cliente = Cliente.query.filter_by(
            email=usuario.username, taller_id=taller_actual_id()
        ).first() if usuario else None
        if not cliente or moto.cliente_id != cliente.id:
            return jsonify({'error': 'Solo puedes eliminar tus propias motos.'}), 403

    dependencias = []
    if Cita.query.filter_by(moto_id=moto.id).first():
        dependencias.append('citas')
    if Diagnostico.query.filter_by(moto_id=moto.id).first():
        dependencias.append('diagnósticos')
    if OrdenServicio.query.filter_by(moto_id=moto.id).first():
        dependencias.append('órdenes de servicio')
    if Factura.query.filter_by(moto_id=moto.id).first():
        dependencias.append('facturas')
    if dependencias:
        return jsonify({
            'error': 'No se puede eliminar la moto porque tiene historial asociado: '
                     + ', '.join(dependencias) + '.'
        }), 409

    registrar_auditoria('moto', moto.id, 'eliminar', antes={
        'placa': moto.placa, 'marca': moto.marca, 'modelo': moto.modelo,
    })
    try:
        db.session.delete(moto)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'No se puede eliminar la moto porque tiene registros relacionados.'
        }), 409
    return jsonify({'mensaje': 'Moto eliminada con éxito'}), 200
