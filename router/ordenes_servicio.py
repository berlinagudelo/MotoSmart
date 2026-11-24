from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from db import db
from modelo.factura import Factura
from modelo.inventario import ItemInventario
from modelo.moto import Moto
from modelo.orden_servicio import OrdenRepuesto, OrdenServicio
from modelo.taller import Taller
from services.notificaciones import enviar_actualizacion_orden_async
from services.paginacion import respuesta_paginada
from services.seguridad import registrar_auditoria
from services.tenencia import taller_actual_id
from services.validacion import cuerpo_json, entero, texto


ordenes_bp = Blueprint('ordenes', __name__)
ESTADOS = ('recibida', 'diagnostico', 'reparacion', 'lista', 'entregada', 'cancelada')
TRANSICIONES = {
    'recibida': {'diagnostico', 'cancelada'},
    'diagnostico': {'reparacion', 'recibida', 'cancelada'},
    'reparacion': {'lista', 'diagnostico', 'cancelada'},
    'lista': {'entregada', 'reparacion', 'cancelada'},
    'entregada': set(),
    'cancelada': set(),
}
MAX_CANTIDAD_REPUESTO = 100_000


def es_personal():
    return get_jwt().get('rol') in ('mecanico', 'admin')


def serializar(orden):
    moto = orden.moto
    return {
        'id': orden.id,
        'numero': orden.numero,
        'descripcion': orden.descripcion,
        'estado': orden.estado,
        'creada_en': orden.creada_en.isoformat(),
        'moto': {
            'id': moto.id,
            'marca': moto.marca,
            'modelo': moto.modelo,
            'placa': moto.placa,
            'cliente': moto.cliente.nombre if moto and moto.cliente else '-',
        } if moto else None,
        'repuestos': [
            {
                'id': repuesto.item.id if repuesto.item else None,
                'nombre': repuesto.item.nombre if repuesto.item else 'Artículo eliminado',
                'unidad': repuesto.item.unidad if repuesto.item else 'unidades',
                'cantidad': repuesto.cantidad,
            }
            for repuesto in orden.repuestos
        ],
    }


def _consulta_ordenes(taller_id):
    return (
        OrdenServicio.query
        .filter_by(taller_id=taller_id)
        .options(
            joinedload(OrdenServicio.moto).joinedload(Moto.cliente),
            selectinload(OrdenServicio.repuestos).joinedload(OrdenRepuesto.item),
        )
        .order_by(OrdenServicio.creada_en.desc(), OrdenServicio.id.desc())
    )


def validar_repuestos(datos):
    if datos is None:
        return {}, None
    if not isinstance(datos, list):
        return None, 'Los repuestos deben enviarse como una lista.'
    acumulados = {}
    for dato in datos:
        if not isinstance(dato, dict):
            return None, 'Revisa el repuesto y la cantidad seleccionada.'
        item_id = entero(dato, 'inventario_id', minimo=1)
        cantidad = entero(dato, 'cantidad', minimo=1, maximo=MAX_CANTIDAD_REPUESTO)
        acumulados[item_id] = acumulados.get(item_id, 0) + cantidad
    return acumulados, None


@ordenes_bp.route('/ordenes-servicio', methods=['GET'])
@jwt_required()
def listar_ordenes():
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede ver las órdenes.'}), 403
    return respuesta_paginada(_consulta_ordenes(taller_actual_id()), serializar)


@ordenes_bp.route('/ordenes-servicio/<int:orden_id>', methods=['GET'])
@jwt_required()
def obtener_orden(orden_id):
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede ver las órdenes.'}), 403
    orden = _consulta_ordenes(taller_actual_id()).filter(
        OrdenServicio.id == orden_id
    ).first()
    if not orden:
        return jsonify({'error': 'Orden de servicio no encontrada.'}), 404
    return jsonify(serializar(orden)), 200


@ordenes_bp.route('/ordenes-servicio', methods=['POST'])
@jwt_required()
def crear_orden():
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede crear órdenes.'}), 403
    try:
        data = cuerpo_json()
        moto_id = entero(data, 'moto_id', minimo=1)
        descripcion = texto(data, 'descripcion', maximo=800)
        repuestos, error = validar_repuestos(data.get('repuestos', []))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if error:
        return jsonify({'error': error}), 400

    taller_id = taller_actual_id()
    clave = request.headers.get('Idempotency-Key', '').strip()[:64] or None
    if clave:
        existente = OrdenServicio.query.filter_by(
            taller_id=taller_id, clave_idempotencia=clave
        ).first()
        if existente:
            return jsonify({
                'mensaje': 'La orden ya fue creada con esta clave de idempotencia.',
                'orden': serializar(existente),
            }), 200

    moto = Moto.query.filter_by(
        id=moto_id, taller_id=taller_id, transferida=False
    ).first()
    if not moto:
        return jsonify({'error': 'La moto seleccionada no existe.'}), 404

    items = ItemInventario.query.filter(
        ItemInventario.id.in_(repuestos.keys()),
        ItemInventario.taller_id == taller_id,
    ).with_for_update().all() if repuestos else []
    if len(items) != len(repuestos):
        return jsonify({'error': 'Uno de los repuestos seleccionados ya no existe.'}), 400
    for item in items:
        if item.cantidad < repuestos[item.id]:
            return jsonify({
                'error': f'Stock insuficiente para {item.nombre}. '
                         f'Disponible: {item.cantidad} {item.unidad}.'
            }), 400

    db.session.execute(
        db.select(Taller).where(Taller.id == taller_id).with_for_update()
    ).scalar_one_or_none()
    ultima = db.session.query(func.max(OrdenServicio.secuencia)).filter_by(
        taller_id=taller_id
    ).scalar() or 0
    secuencia = int(ultima) + 1

    orden = OrdenServicio(
        numero=f'OS-{secuencia:06d}',
        secuencia=secuencia,
        moto_id=moto.id,
        taller_id=taller_id,
        descripcion=descripcion,
        clave_idempotencia=clave,
    )
    db.session.add(orden)
    db.session.flush()
    for item in items:
        cantidad = repuestos[item.id]
        item.cantidad -= cantidad
        db.session.add(OrdenRepuesto(
            orden_id=orden.id, inventario_id=item.id, cantidad=cantidad
        ))
    registrar_auditoria('orden', orden.id, 'crear', despues={
        'numero': orden.numero,
        'moto_id': moto.id,
        'repuestos': [
            {'inventario_id': item.id, 'cantidad': repuestos[item.id]}
            for item in items
        ],
    })
    db.session.commit()
    return jsonify({
        'mensaje': 'Orden creada y repuestos descontados del inventario.',
        'orden': serializar(orden),
    }), 201


@ordenes_bp.route('/ordenes-servicio/<int:orden_id>/estado', methods=['PUT', 'PATCH'])
@jwt_required()
def actualizar_estado(orden_id):
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede actualizar órdenes.'}), 403
    try:
        data = cuerpo_json()
        estado = texto(data, 'estado', maximo=20, lower=True)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if estado not in ESTADOS:
        return jsonify({'error': 'Selecciona un estado válido.'}), 400
    orden = OrdenServicio.query.filter_by(
        id=orden_id, taller_id=taller_actual_id()
    ).first()
    if not orden:
        return jsonify({'error': 'Orden de servicio no encontrada.'}), 404
    if estado == orden.estado:
        return jsonify({
            'mensaje': 'La orden ya tiene ese estado.',
            'orden': serializar(orden),
            'notificacion_programada': False,
        }), 200
    permitidos = TRANSICIONES.get(orden.estado, set())
    if estado not in permitidos:
        return jsonify({
            'error': f'No se puede pasar de "{orden.estado}" a "{estado}". '
                     f'Transiciones permitidas: {", ".join(sorted(permitidos)) or "ninguna"}.'
        }), 409
    antes = orden.estado
    orden.estado = estado
    registrar_auditoria('orden', orden.id, 'cambiar_estado', antes={
        'estado': antes,
    }, despues={'estado': estado})
    db.session.commit()
    enviar_actualizacion_orden_async(orden.id)
    return jsonify({
        'mensaje': 'Estado de la orden actualizado.',
        'orden': serializar(orden),
        'notificacion_programada': True,
    })


@ordenes_bp.route('/ordenes-servicio/<int:orden_id>/cancelar', methods=['POST'])
@jwt_required()
def cancelar_orden(orden_id):
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede cancelar órdenes.'}), 403
    orden = _consulta_ordenes(taller_actual_id()).filter(
        OrdenServicio.id == orden_id
    ).first()
    if not orden:
        return jsonify({'error': 'Orden de servicio no encontrada.'}), 404
    if orden.estado == 'cancelada':
        return jsonify({'mensaje': 'La orden ya está cancelada.', 'orden': serializar(orden)}), 200
    if orden.estado == 'entregada':
        return jsonify({
            'error': 'No se puede cancelar una orden ya entregada.'
        }), 409

    data = request.get_json(silent=True) or {}
    motivo = data.get('motivo') if isinstance(data, dict) else None
    for repuesto in orden.repuestos:
        item = db.session.execute(
            db.select(ItemInventario)
            .where(ItemInventario.id == repuesto.inventario_id)
            .with_for_update()
        ).scalar_one_or_none()
        if item:
            item.cantidad += repuesto.cantidad
    antes = orden.estado
    orden.estado = 'cancelada'
    registrar_auditoria('orden', orden.id, 'cancelar', antes={
        'estado': antes,
    }, despues={
        'estado': 'cancelada',
        'motivo': str(motivo)[:500] if motivo else None,
    })
    db.session.commit()
    return jsonify({
        'mensaje': 'Orden cancelada y stock restaurado.',
        'orden': serializar(orden),
    }), 200


@ordenes_bp.route('/panel-taller', methods=['GET'])
@jwt_required()
def panel_taller():
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede ver el panel.'}), 403
    taller_id = taller_actual_id()
    conteos = dict(
        db.session.query(OrdenServicio.estado, func.count(OrdenServicio.id))
        .filter(OrdenServicio.taller_id == taller_id)
        .group_by(OrdenServicio.estado)
        .all()
    )
    ordenes_activas = sum(
        cantidad for estado, cantidad in conteos.items()
        if estado not in ('lista', 'entregada', 'cancelada')
    )
    desde_dt = datetime.now(timezone.utc) - timedelta(days=30)
    desde_fecha = date.today() - timedelta(days=30)
    servicios_mes = db.session.query(func.count(OrdenServicio.id)).filter(
        OrdenServicio.taller_id == taller_id,
        OrdenServicio.creada_en >= desde_dt,
        OrdenServicio.estado != 'cancelada',
    ).scalar() or 0
    ventas_mes = db.session.query(
        func.coalesce(func.sum(Factura.total), 0)
    ).filter(
        Factura.taller_id == taller_id,
        Factura.fecha >= desde_fecha,
        Factura.estado == 'pagada',
    ).scalar() or 0

    consulta_stock_bajo = ItemInventario.query.filter(
        ItemInventario.taller_id == taller_id,
        ItemInventario.cantidad <= ItemInventario.stock_minimo,
    )
    stock_bajo = consulta_stock_bajo.count()
    items_bajo = consulta_stock_bajo.order_by(
        ItemInventario.cantidad.asc(), ItemInventario.nombre.asc()
    ).limit(5).all()
    recientes = (
        _consulta_ordenes(taller_id)
        .order_by(OrdenServicio.actualizada_en.desc(), OrdenServicio.id.desc())
        .limit(5)
        .all()
    )
    return jsonify({
        'ordenes_activas': ordenes_activas,
        'ordenes_terminadas': conteos.get('entregada', 0),
        'servicios_mes': servicios_mes,
        'stock_bajo': stock_bajo,
        'ventas_mes': float(ventas_mes or 0),
        'alertas_inventario': [
            {
                'nombre': item.nombre,
                'cantidad': item.cantidad,
                'unidad': item.unidad,
                'stock_minimo': item.stock_minimo,
            }
            for item in items_bajo
        ],
        'ordenes_recientes': [serializar(orden) for orden in recientes],
    })
