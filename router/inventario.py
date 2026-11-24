from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy.exc import IntegrityError

from db import db
from modelo.inventario import ItemInventario
from modelo.orden_servicio import OrdenRepuesto
from services.paginacion import respuesta_paginada
from services.seguridad import registrar_auditoria
from services.tenencia import es_titular, taller_actual_id, usuario_actual
from services.validacion import cuerpo_json, entero, texto


inventario_bp = Blueprint('inventario', __name__)
STAFF_ROLES = ('mecanico', 'admin')
CATEGORIAS = {'repuesto', 'herramienta', 'insumo', 'lubricante', 'accesorio'}
UNIDADES = {'unidades', 'litros', 'cajas', 'pares', 'metros'}
MAX_CANTIDAD = 1_000_000


def serializar_item(item):
    estado = (
        'agotado' if item.cantidad == 0
        else 'bajo' if item.cantidad <= item.stock_minimo
        else 'disponible'
    )
    return {
        'id': item.id,
        'nombre': item.nombre,
        'categoria': item.categoria,
        'unidad': item.unidad,
        'cantidad': item.cantidad,
        'stock_minimo': item.stock_minimo,
        'proveedor': item.proveedor or '',
        'estado': estado,
    }


def validar_datos(data):
    nombre = texto(data, 'nombre', maximo=80)
    categoria = texto(data, 'categoria', maximo=30, lower=True)
    unidad = texto(
        data, 'unidad', requerido=False, default='unidades', maximo=20, lower=True
    )
    proveedor = texto(
        data, 'proveedor', requerido=False, default='', maximo=100, permitir_vacio=True
    )
    if categoria not in CATEGORIAS:
        raise ValueError('Selecciona una categoría válida.')
    if unidad not in UNIDADES:
        raise ValueError('Selecciona una unidad válida.')
    cantidad = entero(data, 'cantidad', minimo=0, maximo=MAX_CANTIDAD)
    stock_minimo = entero(data, 'stock_minimo', minimo=0, maximo=MAX_CANTIDAD)
    return {
        'nombre': nombre,
        'categoria': categoria,
        'unidad': unidad,
        'cantidad': cantidad,
        'stock_minimo': stock_minimo,
        'proveedor': proveedor or None,
    }


def puede_gestionar():
    return get_jwt().get('rol') in STAFF_ROLES


def puede_administrar_inventario():
    """Solo el titular del taller (o un administrador) cambia existencias."""
    if get_jwt().get('rol') == 'admin':
        return True
    return es_titular(usuario_actual())


@inventario_bp.route('/inventario', methods=['GET'])
@jwt_required()
def listar_inventario():
    if not puede_gestionar():
        return jsonify({'error': 'No tienes permisos para consultar el inventario'}), 403
    consulta = ItemInventario.query.filter_by(
        taller_id=taller_actual_id()
    ).order_by(ItemInventario.nombre.asc(), ItemInventario.id.asc())
    return respuesta_paginada(consulta, serializar_item)


@inventario_bp.route('/inventario', methods=['POST'])
@jwt_required()
def crear_item():
    if not puede_administrar_inventario():
        return jsonify({'error': 'Solo el titular del taller puede agregar artículos al inventario.'}), 403
    try:
        datos = validar_datos(cuerpo_json())
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    taller_id = taller_actual_id()
    if ItemInventario.query.filter_by(taller_id=taller_id, nombre=datos['nombre']).first():
        return jsonify({'error': 'Ya existe un artículo con ese nombre en el inventario.'}), 409
    item = ItemInventario(**datos, taller_id=taller_id)
    db.session.add(item)
    try:
        db.session.flush()
        registrar_auditoria('inventario', item.id, 'crear', despues=datos)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Ya existe un artículo con ese nombre en el inventario.'}), 409
    return jsonify({'mensaje': 'Ítem agregado al inventario.', 'item': serializar_item(item)}), 201


@inventario_bp.route('/inventario/<int:item_id>', methods=['GET'])
@jwt_required()
def obtener_item(item_id):
    if not puede_gestionar():
        return jsonify({'error': 'No tienes permisos para consultar el inventario'}), 403
    item = ItemInventario.query.filter_by(
        id=item_id, taller_id=taller_actual_id()
    ).first()
    if not item:
        return jsonify({'error': 'Artículo de inventario no encontrado.'}), 404
    return jsonify(serializar_item(item)), 200


@inventario_bp.route('/inventario/<int:item_id>', methods=['PUT', 'PATCH'])
@jwt_required()
def actualizar_item(item_id):
    if not puede_administrar_inventario():
        return jsonify({'error': 'Solo el titular del taller puede editar el inventario.'}), 403
    item = ItemInventario.query.filter_by(
        id=item_id, taller_id=taller_actual_id()
    ).first()
    if not item:
        return jsonify({'error': 'Artículo de inventario no encontrado.'}), 404
    try:
        datos = validar_datos(cuerpo_json())
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    duplicado = ItemInventario.query.filter(
        ItemInventario.taller_id == taller_actual_id(),
        ItemInventario.nombre == datos['nombre'],
        ItemInventario.id != item.id,
    ).first()
    if duplicado:
        return jsonify({'error': 'Ya existe un artículo con ese nombre en el inventario.'}), 409
    antes = serializar_item(item)
    for campo, valor in datos.items():
        setattr(item, campo, valor)
    try:
        registrar_auditoria('inventario', item.id, 'actualizar', antes=antes, despues=datos)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Ya existe un artículo con ese nombre en el inventario.'}), 409
    return jsonify({'mensaje': 'Ítem actualizado.', 'item': serializar_item(item)})


@inventario_bp.route('/inventario/<int:item_id>', methods=['DELETE'])
@jwt_required()
def eliminar_item(item_id):
    if not puede_administrar_inventario():
        return jsonify({'error': 'Solo el titular del taller puede eliminar artículos del inventario.'}), 403
    item = ItemInventario.query.filter_by(
        id=item_id, taller_id=taller_actual_id()
    ).first()
    if not item:
        return jsonify({'error': 'Artículo de inventario no encontrado.'}), 404
    if OrdenRepuesto.query.filter_by(inventario_id=item.id).first():
        return jsonify({
            'error': 'No se puede eliminar el artículo porque está asociado a órdenes de servicio. '
                     'Ajusta su cantidad a cero si ya no lo usas.'
        }), 409
    antes = serializar_item(item)
    registrar_auditoria('inventario', item.id, 'eliminar', antes=antes)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'mensaje': 'Ítem eliminado del inventario.'})
