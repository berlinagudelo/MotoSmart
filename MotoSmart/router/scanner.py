import os
import re
import json
import uuid

import easyocr
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from db import db
from modelo.clientes import Cliente
from modelo.diagnostico import Diagnostico
from modelo.moto import Moto
from modelo.usuario import Usuario
from services.priorizacion import evaluar_prioridad

scanner_bp = Blueprint('scanner', __name__)
reader = easyocr.Reader(['es', 'en'])

CODIGO_OBD = re.compile(r'\b([PBCU])\s*([0-9A-F]{3,5})\b', re.IGNORECASE)


def separar_lectura_ocr(lineas):
    """Relaciona cada codigo con la descripcion que aparece despues en la foto."""
    if isinstance(lineas, str):
        lineas = lineas.splitlines() or [lineas]

    detalles = []
    actual = None

    def guardar_actual():
        if not actual:
            return
        descripcion = ' '.join(actual['fragmentos']).strip(' -:|')
        detalles.append({
            'codigo': actual['codigo'],
            'descripcion': descripcion or 'Requiere revision del mecanico.'
        })

    for linea_original in lineas:
        linea = ' '.join(linea_original.strip().split())
        if not linea:
            continue
        coincidencias = list(CODIGO_OBD.finditer(linea))
        if not coincidencias:
            if actual:
                actual['fragmentos'].append(linea)
            continue

        for indice, coincidencia in enumerate(coincidencias):
            guardar_actual()
            codigo = f"{coincidencia.group(1).upper()}{coincidencia.group(2).upper()}"
            final = coincidencias[indice + 1].start() if indice + 1 < len(coincidencias) else len(linea)
            resto = linea[coincidencia.end():final].strip(' -:|')
            actual = {'codigo': codigo, 'fragmentos': [resto] if resto else []}

    guardar_actual()
    if not detalles:
        lectura = ' '.join(' '.join(linea.split()) for linea in lineas).strip()
        detalles = [{'codigo': 'SIN_CODIGO', 'descripcion': lectura or 'No se detecto un codigo de error legible.'}]

    codigo = ', '.join(item['codigo'] for item in detalles)
    descripcion = '\n'.join(f"{item['codigo']} - {item['descripcion']}" for item in detalles)
    return codigo, descripcion, detalles


@scanner_bp.route('/upload_scanner', methods=['POST'])
@jwt_required()
def upload_scanner():
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecanicos pueden procesar diagnosticos'}), 403
    if 'imagen' not in request.files:
        return jsonify({'error': 'No se encontro el archivo de imagen'}), 400

    moto = Moto.query.get(request.form.get('moto_id'))
    if not moto:
        return jsonify({'error': 'La moto seleccionada no existe'}), 404

    file = request.files['imagen']
    filename = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
    os.makedirs('temp_uploads', exist_ok=True)
    img_path = os.path.join('temp_uploads', filename)
    file.save(img_path)
    try:
        try:
            resultados = reader.readtext(img_path)
            lineas = [resultado[1] for resultado in resultados]
        except Exception as error:
            return jsonify({'error': f'No se pudo procesar la imagen: {error}'}), 400
        codigo, descripcion, detalles = separar_lectura_ocr(lineas)
        analisis = evaluar_prioridad(detalles)
        diagnostico = Diagnostico(
            moto_id=moto.id,
            codigo_error=codigo,
            descripcion=descripcion,
            detalle_codigos=json.dumps(detalles),
            prioridad=analisis['prioridad'],
            motivo_prioridad=analisis['motivo_prioridad'],
            recomendacion=analisis['recomendacion']
        )
        db.session.add(diagnostico)
        db.session.commit()
        return jsonify({
            'mensaje': 'Diagnostico guardado',
            'codigo_error': diagnostico.codigo_error,
            'descripcion': diagnostico.descripcion,
            'detalles': detalles,
            **analisis
        }), 201
    finally:
        if os.path.exists(img_path):
            os.remove(img_path)


def serializar_diagnostico(diagnostico):
    try:
        detalles = json.loads(diagnostico.detalle_codigos) if diagnostico.detalle_codigos else []
    except (TypeError, json.JSONDecodeError):
        detalles = []
    if not detalles:
        detalles = [{'codigo': diagnostico.codigo_error, 'descripcion': diagnostico.descripcion or 'Sin descripcion disponible.'}]
    analisis = evaluar_prioridad(detalles)
    return {
        'id': diagnostico.id,
        'moto_id': diagnostico.moto_id,
        'moto': {
            'marca': diagnostico.moto.marca,
            'modelo': diagnostico.moto.modelo,
            'placa': diagnostico.moto.placa
        } if diagnostico.moto else None,
        'codigo_error': diagnostico.codigo_error,
        'descripcion': diagnostico.descripcion or 'Sin descripcion disponible.',
        'detalles': detalles,
        'prioridad': diagnostico.prioridad or analisis['prioridad'],
        'peso_prioridad': analisis['peso_prioridad'],
        'motivo_prioridad': diagnostico.motivo_prioridad or analisis['motivo_prioridad'],
        'recomendacion': diagnostico.recomendacion or analisis['recomendacion'],
        'fecha': diagnostico.fecha.isoformat()
    }


@scanner_bp.route('/diagnosticos', methods=['GET'])
@jwt_required()
def listar_diagnosticos():
    if get_jwt().get('rol') not in ('mecanico', 'admin'):
        return jsonify({'error': 'No tienes permisos para esta accion'}), 403
    return jsonify([serializar_diagnostico(diag) for diag in Diagnostico.query.all()])


@scanner_bp.route('/prioridades', methods=['GET'])
@jwt_required()
def listar_prioridades():
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecanicos pueden ver la cola de prioridades'}), 403

    recientes_por_moto = {}
    for diagnostico in Diagnostico.query.order_by(Diagnostico.fecha.desc()).all():
        recientes_por_moto.setdefault(diagnostico.moto_id, diagnostico)
    resultados = [serializar_diagnostico(item) for item in recientes_por_moto.values()]
    resultados.sort(key=lambda item: item['peso_prioridad'], reverse=True)
    return jsonify(resultados)


@scanner_bp.route('/diagnosticos/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_diagnostico(id):
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecanicos pueden eliminar diagnosticos'}), 403
    diagnostico = Diagnostico.query.get_or_404(id)
    db.session.delete(diagnostico)
    db.session.commit()
    return jsonify({'mensaje': 'Diagnostico eliminado con exito'})


@scanner_bp.route('/mis_diagnosticos', methods=['GET'])
@jwt_required()
def mis_diagnosticos():
    if get_jwt().get('rol') != 'cliente':
        return jsonify({'error': 'Esta vista es solo para clientes'}), 403

    usuario = Usuario.query.get(int(get_jwt_identity()))
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    cliente = Cliente.query.filter_by(email=usuario.username).first()
    if not cliente:
        return jsonify([])

    diagnosticos = Diagnostico.query.join(Moto).filter(Moto.cliente_id == cliente.id).all()
    return jsonify([serializar_diagnostico(diag) for diag in diagnosticos])
