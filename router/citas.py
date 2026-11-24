from datetime import date, timedelta

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from db import db
from modelo.citas import Cita
from modelo.clientes import Cliente
from modelo.moto import Moto
from services.paginacion import respuesta_paginada
from services.seguridad import registrar_auditoria
from services.tenencia import taller_actual_id, usuario_actual
from services.validacion import cuerpo_json, entero, fecha_campo, texto


citas_bp = Blueprint('citas', __name__)
DIAS_MAXIMOS_AGENDA = 730


def es_personal():
    return get_jwt().get('rol') in ('mecanico', 'admin')


def cliente_actual(crear=False):
    usuario = usuario_actual()
    if not usuario:
        return None
    cliente = Cliente.query.filter_by(
        email=usuario.username, taller_id=usuario.taller_id
    ).first()
    if not cliente and crear:
        cliente = Cliente(
            nombre=usuario.nombre or usuario.username.split('@')[0],
            email=usuario.username,
            taller_id=usuario.taller_id,
        )
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
            'cliente': moto.cliente.nombre if moto.cliente else None,
        } if moto else None,
    }


def _fecha_valida(data, *, permitir_pasado=False):
    minimo = None if permitir_pasado else date.today()
    return fecha_campo(
        data,
        'fecha',
        minimo=minimo,
        maximo=date.today() + timedelta(days=DIAS_MAXIMOS_AGENDA),
    )


@citas_bp.route('/citas', methods=['POST'])
@jwt_required()
def crear_cita():
    if get_jwt().get('rol') != 'cliente':
        return jsonify({'error': 'Solo clientes pueden agendar citas'}), 403
    data = cuerpo_json()
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    cliente = cliente_actual(crear=True)
    moto_id = entero(data, 'moto_id', minimo=1)
    moto = Moto.query.filter_by(
        id=moto_id,
        cliente_id=cliente.id,
        taller_id=taller_actual_id(),
        transferida=False,
    ).first() if cliente else None
    if not moto:
        return jsonify({'error': 'La moto seleccionada no existe'}), 404
    fecha = _fecha_valida(data)
    descripcion = texto(
        data, 'descripcion', requerido=False, default='', maximo=200,
        permitir_vacio=True,
    )
    if Cita.query.filter_by(moto_id=moto.id, fecha=fecha).first():
        return jsonify({'error': 'Ya existe una cita para esa moto en esa fecha.'}), 409

    cita = Cita(
        fecha=fecha,
        descripcion=descripcion,
        moto_id=moto.id,
        taller_id=taller_actual_id(),
    )
    db.session.add(cita)
    try:
        db.session.flush()
        registrar_auditoria('cita', cita.id, 'crear', despues={
            'moto_id': moto.id, 'fecha': fecha.isoformat(),
        })
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Ya existe una cita para esa moto en esa fecha.'}), 409
    return jsonify({'mensaje': 'Cita agendada con éxito', 'cita': serializar_cita(cita)}), 201


@citas_bp.route('/citas/detalle', methods=['GET'])
@jwt_required()
def listar_citas_detalle():
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede ver las citas'}), 403
    consulta = (
        Cita.query
        .filter_by(taller_id=taller_actual_id())
        .options(joinedload(Cita.moto).joinedload(Moto.cliente))
        .order_by(Cita.fecha.asc(), Cita.id.asc())
    )
    return respuesta_paginada(consulta, serializar_cita)


@citas_bp.route('/mis_citas', methods=['GET'])
@jwt_required()
def listar_mis_citas():
    if get_jwt().get('rol') != 'cliente':
        return jsonify({'error': 'Esta vista es solo para clientes'}), 403
    cliente = cliente_actual()
    if not cliente:
        return jsonify([])
    consulta = (
        Cita.query
        .filter_by(taller_id=taller_actual_id())
        .join(Moto)
        .filter(Moto.cliente_id == cliente.id)
        .options(joinedload(Cita.moto).joinedload(Moto.cliente))
        .order_by(Cita.fecha.asc(), Cita.id.asc())
    )
    return respuesta_paginada(consulta, serializar_cita)


@citas_bp.route('/citas/<int:id>', methods=['GET'])
@jwt_required()
def obtener_cita(id):
    cita = (
        Cita.query
        .filter_by(id=id, taller_id=taller_actual_id())
        .options(joinedload(Cita.moto).joinedload(Moto.cliente))
        .first()
    )
    if not cita:
        return jsonify({'error': 'Cita no encontrada.'}), 404
    if not es_personal():
        cliente = cliente_actual()
        if not cliente or cita.moto.cliente_id != cliente.id:
            return jsonify({'error': 'No tienes permisos para consultar esta cita'}), 403
    return jsonify(serializar_cita(cita)), 200


@citas_bp.route('/citas/<int:id>', methods=['PUT', 'PATCH'])
@jwt_required()
def actualizar_cita(id):
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede editar citas'}), 403
    cita = Cita.query.filter_by(
        id=id, taller_id=taller_actual_id()
    ).first()
    if not cita:
        return jsonify({'error': 'Cita no encontrada.'}), 404
    data = cuerpo_json()
    antes = {
        'fecha': cita.fecha.isoformat(),
        'descripcion': cita.descripcion,
        'moto_id': cita.moto_id,
    }
    if 'fecha' in data:
        nueva_fecha = _fecha_valida(data, permitir_pasado=cita.fecha < date.today())
        duplicada = Cita.query.filter(
            Cita.moto_id == cita.moto_id,
            Cita.fecha == nueva_fecha,
            Cita.id != cita.id,
        ).first()
        if duplicada:
            return jsonify({'error': 'Ya existe una cita para esa moto en esa fecha.'}), 409
        cita.fecha = nueva_fecha
    if 'moto_id' in data:
        moto_id = entero(data, 'moto_id', minimo=1)
        moto = Moto.query.filter_by(
            id=moto_id,
            taller_id=taller_actual_id(),
            transferida=False,
        ).first()
        if not moto:
            return jsonify({'error': 'La moto seleccionada no existe'}), 404
        duplicada = Cita.query.filter(
            Cita.moto_id == moto.id,
            Cita.fecha == cita.fecha,
            Cita.id != cita.id,
        ).first()
        if duplicada:
            return jsonify({'error': 'Ya existe una cita para esa moto en esa fecha.'}), 409
        cita.moto_id = moto.id
    if 'descripcion' in data:
        cita.descripcion = texto(
            data, 'descripcion', requerido=False, default='', maximo=200,
            permitir_vacio=True,
        )
    registrar_auditoria('cita', cita.id, 'actualizar', antes=antes, despues={
        'fecha': cita.fecha.isoformat(),
        'descripcion': cita.descripcion,
        'moto_id': cita.moto_id,
    })
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Ya existe una cita para esa moto en esa fecha.'}), 409
    return jsonify({'mensaje': 'Cita actualizada con éxito', 'cita': serializar_cita(cita)})


@citas_bp.route('/citas/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_cita(id):
    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    cita = Cita.query.filter_by(
        id=id, taller_id=usuario.taller_id
    ).first()
    if not cita:
        return jsonify({'error': 'Cita no encontrada.'}), 404
    if get_jwt().get('rol') == 'cliente':
        cliente = Cliente.query.filter_by(
            email=usuario.username, taller_id=usuario.taller_id
        ).first()
        if not cliente or not cita.moto or cita.moto.cliente_id != cliente.id:
            return jsonify({'error': 'No puedes cancelar una cita de otro cliente.'}), 403
    elif not es_personal():
        return jsonify({'error': 'No tienes permisos para eliminar citas'}), 403
    registrar_auditoria('cita', cita.id, 'eliminar', antes={
        'fecha': cita.fecha.isoformat(), 'moto_id': cita.moto_id,
    })
    db.session.delete(cita)
    db.session.commit()
    return jsonify({'mensaje': 'Cita eliminada con éxito'})
