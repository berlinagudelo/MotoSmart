from datetime import date, timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required

from db import db
from modelo.inventario import ItemInventario
from modelo.factura import Factura
from modelo.moto import Moto
from modelo.orden_servicio import OrdenRepuesto, OrdenServicio
from services.notificaciones import enviar_actualizacion_orden
from services.tenencia import taller_actual_id


ordenes_bp = Blueprint('ordenes', __name__)
ESTADOS = ('recibida', 'diagnostico', 'reparacion', 'lista', 'entregada')


def es_personal():
    return get_jwt().get('rol') in ('mecanico', 'admin')


def serializar(orden):
    moto = orden.moto
    return {
        'id': orden.id, 'numero': orden.numero, 'descripcion': orden.descripcion,
        'estado': orden.estado, 'creada_en': orden.creada_en.isoformat(),
        'moto': {'id': moto.id, 'marca': moto.marca, 'modelo': moto.modelo, 'placa': moto.placa,
                 'cliente': moto.cliente.nombre if moto and moto.cliente else '-'} if moto else None,
        'repuestos': [{'id': repuesto.item.id, 'nombre': repuesto.item.nombre,
                       'unidad': repuesto.item.unidad, 'cantidad': repuesto.cantidad}
                      for repuesto in orden.repuestos]
    }


def validar_repuestos(datos):
    if not isinstance(datos, list):
        return None, 'Los repuestos deben enviarse como una lista.'
    acumulados = {}
    for dato in datos:
        try:
            item_id, cantidad = int(dato.get('inventario_id')), int(dato.get('cantidad'))
        except (AttributeError, TypeError, ValueError):
            return None, 'Revisa el repuesto y la cantidad seleccionada.'
        if cantidad < 1:
            return None, 'La cantidad de cada repuesto debe ser mayor a cero.'
        acumulados[item_id] = acumulados.get(item_id, 0) + cantidad
    return acumulados, None


@ordenes_bp.route('/ordenes-servicio', methods=['GET'])
@jwt_required()
def listar_ordenes():
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede ver las órdenes.'}), 403
    ordenes = OrdenServicio.query.filter_by(
        taller_id=taller_actual_id()
    ).order_by(OrdenServicio.creada_en.desc()).all()
    return jsonify([serializar(orden) for orden in ordenes])


@ordenes_bp.route('/ordenes-servicio', methods=['POST'])
@jwt_required()
def crear_orden():
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede crear órdenes.'}), 403
    data = request.get_json(silent=True) or {}
    try:
        moto_id = int(data.get('moto_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Selecciona una moto válida.'}), 400
    descripcion = str(data.get('descripcion', '')).strip()
    if not descripcion or len(descripcion) > 800:
        return jsonify({'error': 'Describe el servicio en máximo 800 caracteres.'}), 400
    taller_id = taller_actual_id()
    moto = Moto.query.filter_by(
        id=moto_id, taller_id=taller_id, transferida=False
    ).first()
    if not moto:
        return jsonify({'error': 'La moto seleccionada no existe.'}), 404
    repuestos, error = validar_repuestos(data.get('repuestos', []))
    if error:
        return jsonify({'error': error}), 400

    items = ItemInventario.query.filter(
        ItemInventario.id.in_(repuestos.keys()),
        ItemInventario.taller_id == taller_id,
    ).with_for_update().all() if repuestos else []
    if len(items) != len(repuestos):
        return jsonify({'error': 'Uno de los repuestos seleccionados ya no existe.'}), 400
    for item in items:
        if item.cantidad < repuestos[item.id]:
            return jsonify({'error': f'Stock insuficiente para {item.nombre}. Disponible: {item.cantidad} {item.unidad}.'}), 400

    orden = OrdenServicio(
        numero='PENDIENTE',
        moto_id=moto.id,
        taller_id=taller_id,
        descripcion=descripcion,
    )
    db.session.add(orden)
    db.session.flush()
    orden.numero = f'OS-{orden.id:06d}'
    for item in items:
        cantidad = repuestos[item.id]
        item.cantidad -= cantidad
        db.session.add(OrdenRepuesto(orden_id=orden.id, inventario_id=item.id, cantidad=cantidad))
    db.session.commit()
    return jsonify({'mensaje': 'Orden creada y repuestos descontados del inventario.', 'orden': serializar(orden)}), 201


@ordenes_bp.route('/ordenes-servicio/<int:orden_id>/estado', methods=['PUT'])
@jwt_required()
def actualizar_estado(orden_id):
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede actualizar órdenes.'}), 403
    estado = str((request.get_json(silent=True) or {}).get('estado', '')).strip().lower()
    if estado not in ESTADOS:
        return jsonify({'error': 'Selecciona un estado válido.'}), 400
    orden = OrdenServicio.query.filter_by(
        id=orden_id, taller_id=taller_actual_id()
    ).first_or_404()
    orden.estado = estado
    db.session.commit()
    notificacion_enviada = enviar_actualizacion_orden(orden)
    return jsonify({
        'mensaje': 'Estado de la orden actualizado.',
        'orden': serializar(orden),
        'notificacion_enviada': notificacion_enviada
    })


@ordenes_bp.route('/panel-taller', methods=['GET'])
@jwt_required()
def panel_taller():
    if not es_personal():
        return jsonify({'error': 'Solo el personal del taller puede ver el panel.'}), 403
    taller_id = taller_actual_id()
    ordenes = OrdenServicio.query.filter_by(taller_id=taller_id).all()
    consulta_stock_bajo = ItemInventario.query.filter(
        ItemInventario.taller_id == taller_id,
        ItemInventario.cantidad <= ItemInventario.stock_minimo
    )
    stock_bajo = consulta_stock_bajo.count()
    items_bajo = consulta_stock_bajo.order_by(
        ItemInventario.cantidad.asc(), ItemInventario.nombre.asc()
    ).limit(5).all()
    desde = date.today() - timedelta(days=30)
    ventas_mes = sum(float(factura.total) for factura in Factura.query.filter(
        Factura.taller_id == taller_id,
        Factura.fecha >= desde,
        Factura.estado == 'pagada',
    ).all())
    return jsonify({
        'ordenes_activas': sum(orden.estado not in ('lista', 'entregada') for orden in ordenes),
        'ordenes_terminadas': sum(orden.estado == 'entregada' for orden in ordenes),
        'servicios_mes': sum(orden.creada_en.date() >= desde for orden in ordenes),
        'stock_bajo': stock_bajo,
        'ventas_mes': ventas_mes,
        'alertas_inventario': [
            {'nombre': item.nombre, 'cantidad': item.cantidad, 'unidad': item.unidad,
             'stock_minimo': item.stock_minimo}
            for item in items_bajo
        ],
        'ordenes_recientes': [serializar(orden) for orden in
                              OrdenServicio.query.filter_by(taller_id=taller_id)
                              .order_by(OrdenServicio.actualizada_en.desc()).limit(5).all()]
    })
