from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required

from db import db
from modelo.inventario import ItemInventario
from services.tenencia import es_titular, taller_actual_id, usuario_actual


inventario_bp = Blueprint('inventario', __name__)
STAFF_ROLES = ('mecanico', 'admin')
CATEGORIAS = {'repuesto', 'herramienta', 'insumo', 'lubricante', 'accesorio'}
UNIDADES = {'unidades', 'litros', 'cajas', 'pares', 'metros'}


def serializar_item(item):
    estado = 'agotado' if item.cantidad == 0 else 'bajo' if item.cantidad <= item.stock_minimo else 'disponible'
    return {'id': item.id, 'nombre': item.nombre, 'categoria': item.categoria,
            'unidad': item.unidad, 'cantidad': item.cantidad,
            'stock_minimo': item.stock_minimo, 'proveedor': item.proveedor or '', 'estado': estado}


def validar_datos(data):
    if not isinstance(data, dict):
        return None, 'Datos de inventario inválidos.'
    nombre = str(data.get('nombre', '')).strip()
    categoria = str(data.get('categoria', '')).strip().lower()
    unidad = str(data.get('unidad', 'unidades')).strip().lower()
    proveedor = str(data.get('proveedor', '')).strip()
    if not nombre or len(nombre) > 80:
        return None, 'Ingresa un nombre de ítem válido.'
    if categoria not in CATEGORIAS or unidad not in UNIDADES:
        return None, 'Selecciona una categoría y unidad válidas.'
    if len(proveedor) > 100:
        return None, 'El proveedor no puede superar 100 caracteres.'
    try:
        cantidad, stock_minimo = int(data.get('cantidad')), int(data.get('stock_minimo'))
    except (TypeError, ValueError):
        return None, 'Cantidad y stock mínimo deben ser números enteros.'
    if cantidad < 0 or stock_minimo < 0:
        return None, 'La cantidad y el stock mínimo no pueden ser negativos.'
    return {'nombre': nombre, 'categoria': categoria, 'unidad': unidad, 'cantidad': cantidad,
            'stock_minimo': stock_minimo, 'proveedor': proveedor or None}, None


def puede_gestionar():
    return get_jwt().get('rol') in STAFF_ROLES


def puede_administrar_inventario():
    """Solo el titular del taller puede cambiar existencias."""
    return es_titular(usuario_actual())


@inventario_bp.route('/inventario', methods=['GET'])
@jwt_required()
def listar_inventario():
    if not puede_gestionar():
        return jsonify({'error': 'No tienes permisos para consultar el inventario'}), 403
    items = ItemInventario.query.filter_by(
        taller_id=taller_actual_id()
    ).order_by(ItemInventario.nombre.asc()).all()
    return jsonify([serializar_item(item) for item in items])


@inventario_bp.route('/inventario', methods=['POST'])
@jwt_required()
def crear_item():
    if not puede_administrar_inventario():
        return jsonify({'error': 'Solo el titular del taller puede agregar artículos al inventario.'}), 403
    datos, error = validar_datos(request.get_json(silent=True))
    if error:
        return jsonify({'error': error}), 400
    item = ItemInventario(**datos, taller_id=taller_actual_id())
    db.session.add(item)
    db.session.commit()
    return jsonify({'mensaje': 'Ítem agregado al inventario.', 'item': serializar_item(item)}), 201


@inventario_bp.route('/inventario/<int:item_id>', methods=['PUT'])
@jwt_required()
def actualizar_item(item_id):
    if not puede_administrar_inventario():
        return jsonify({'error': 'Solo el titular del taller puede editar el inventario.'}), 403
    datos, error = validar_datos(request.get_json(silent=True))
    if error:
        return jsonify({'error': error}), 400
    item = ItemInventario.query.filter_by(
        id=item_id, taller_id=taller_actual_id()
    ).first_or_404()
    for campo, valor in datos.items():
        setattr(item, campo, valor)
    db.session.commit()
    return jsonify({'mensaje': 'Ítem actualizado.', 'item': serializar_item(item)})


@inventario_bp.route('/inventario/<int:item_id>', methods=['DELETE'])
@jwt_required()
def eliminar_item(item_id):
    if not puede_administrar_inventario():
        return jsonify({'error': 'Solo el titular del taller puede eliminar artículos del inventario.'}), 403
    item = ItemInventario.query.filter_by(
        id=item_id, taller_id=taller_actual_id()
    ).first_or_404()
    db.session.delete(item)
    db.session.commit()
    return jsonify({'mensaje': 'Ítem eliminado del inventario.'})
