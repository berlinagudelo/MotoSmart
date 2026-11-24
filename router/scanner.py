import json
import logging
import os

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from db import db
from modelo.clientes import Cliente
from modelo.diagnostico import Diagnostico
from modelo.moto import Moto
from modelo.trabajo_ocr import TrabajoOCR
from services.ocr_procesamiento import separar_lectura_ocr  # re-export histórico
from services.ocr_queue import crear_trabajo, serializar_trabajo
from services.paginacion import respuesta_paginada
from services.priorizacion import evaluar_prioridad
from services.seguridad import registrar_auditoria
from services.tenencia import taller_actual_id, usuario_actual
from services.validacion import cuerpo_json, entero


logger = logging.getLogger('motorsmart.scanner')
scanner_bp = Blueprint('scanner', __name__)

EXTENSIONES = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}


def _tipo_imagen(archivo):
    cabecera = archivo.stream.read(16)
    archivo.stream.seek(0)
    if cabecera.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if cabecera.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if cabecera[:4] == b'RIFF' and cabecera[8:12] == b'WEBP':
        return '.webp'
    if cabecera.startswith(b'BM'):
        return '.bmp'
    return None


@scanner_bp.route('/upload_scanner', methods=['POST'])
@jwt_required()
def upload_scanner():
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecánicos pueden procesar diagnósticos'}), 403
    if 'imagen' not in request.files:
        return jsonify({'error': 'No se encontró el archivo de imagen'}), 400

    taller_id = taller_actual_id()
    try:
        moto_id = entero({'moto_id': request.form.get('moto_id')}, 'moto_id', minimo=1)
    except ValueError:
        return jsonify({'error': 'Selecciona una moto válida.'}), 400
    moto = Moto.query.filter_by(
        id=moto_id, taller_id=taller_id, transferida=False
    ).first()
    if not moto:
        return jsonify({'error': 'La moto seleccionada no existe'}), 404
    if moto.tipo_tecnologia != 'electronica':
        return jsonify({
            'error': 'El escáner solo se usa para motos electrónicas. '
                     'Registra la revisión mecánica manual.'
        }), 400

    archivo = request.files['imagen']
    if not archivo or not archivo.filename:
        return jsonify({'error': 'No se encontró el archivo de imagen'}), 400
    extension_original = os.path.splitext(archivo.filename)[1].lower()
    if extension_original not in EXTENSIONES:
        return jsonify({
            'error': 'Formato no permitido. Usa JPG, PNG, WEBP o BMP.'
        }), 400
    extension = _tipo_imagen(archivo)
    if extension is None:
        return jsonify({
            'error': 'El archivo no es una imagen válida (JPG, PNG, WEBP o BMP).'
        }), 400

    maximo = current_app.config.get('MAX_CONTENT_LENGTH', 10 * 1024 * 1024)
    archivo.stream.seek(0, os.SEEK_END)
    tamano = archivo.stream.tell()
    archivo.stream.seek(0)
    if tamano <= 0 or tamano > maximo:
        return jsonify({'error': 'La imagen está vacía o supera el tamaño máximo permitido.'}), 413

    usuario = usuario_actual()
    if usuario is None:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    try:
        trabajo = crear_trabajo(moto, usuario, archivo, extension, tamano)
    except OSError:
        logger.exception('No se pudo guardar la imagen del trabajo OCR.')
        return jsonify({
            'error': 'No se pudo guardar la imagen para procesamiento. Inténtalo de nuevo.'
        }), 503
    return jsonify({
        'mensaje': 'Imagen recibida. El diagnóstico se está procesando.',
        'trabajo': serializar_trabajo(trabajo),
        'estado_url': f'/scanner/trabajos/{trabajo.id}',
    }), 202


@scanner_bp.route('/scanner/trabajos/<int:id>', methods=['GET'])
@jwt_required()
def estado_trabajo_ocr(id):
    if get_jwt().get('rol') not in ('mecanico', 'admin'):
        return jsonify({'error': 'Solo mecánicos pueden consultar diagnósticos'}), 403
    trabajo = TrabajoOCR.query.filter_by(
        id=id, taller_id=taller_actual_id()
    ).first()
    if not trabajo:
        return jsonify({'error': 'Trabajo no encontrado.'}), 404
    return jsonify({'trabajo': serializar_trabajo(trabajo)}), 200


def serializar_diagnostico(diagnostico):
    try:
        detalles = json.loads(diagnostico.detalle_codigos) if diagnostico.detalle_codigos else []
    except (TypeError, json.JSONDecodeError):
        detalles = []
    if not detalles:
        detalles = [{
            'codigo': diagnostico.codigo_error,
            'descripcion': diagnostico.descripcion or 'Sin descripción disponible.',
        }]
    analisis = evaluar_prioridad(detalles)
    prioridad = diagnostico.prioridad or analisis['prioridad']
    pesos_manual = {'BAJA': 1, 'MEDIA': 2, 'ALTA': 3}
    peso_prioridad = (
        pesos_manual.get(prioridad, analisis['peso_prioridad'])
        if diagnostico.codigo_error == 'REVISION MECANICA'
        else analisis['peso_prioridad']
    )
    return {
        'id': diagnostico.id,
        'moto_id': diagnostico.moto_id,
        'moto': {
            'marca': diagnostico.moto.marca,
            'modelo': diagnostico.moto.modelo,
            'placa': diagnostico.moto.placa,
            'tipo_tecnologia': diagnostico.moto.tipo_tecnologia or 'electronica',
        } if diagnostico.moto else None,
        'codigo_error': diagnostico.codigo_error,
        'descripcion': diagnostico.descripcion or 'Sin descripción disponible.',
        'detalles': detalles,
        'prioridad': prioridad,
        'peso_prioridad': peso_prioridad,
        'motivo_prioridad': diagnostico.motivo_prioridad or analisis['motivo_prioridad'],
        'recomendacion': diagnostico.recomendacion or analisis['recomendacion'],
        'fecha': diagnostico.fecha.isoformat() if diagnostico.fecha else None,
    }


@scanner_bp.route('/diagnosticos', methods=['GET'])
@jwt_required()
def listar_diagnosticos():
    if get_jwt().get('rol') not in ('mecanico', 'admin'):
        return jsonify({'error': 'No tienes permisos para esta acción'}), 403
    consulta = (
        Diagnostico.query
        .filter_by(taller_id=taller_actual_id())
        .options(joinedload(Diagnostico.moto))
        .order_by(Diagnostico.fecha.desc(), Diagnostico.id.desc())
    )
    return respuesta_paginada(consulta, serializar_diagnostico)


@scanner_bp.route('/prioridades', methods=['GET'])
@jwt_required()
def listar_prioridades():
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecánicos pueden ver la cola de prioridades'}), 403

    taller_id = taller_actual_id()
    recientes = (
        db.session.query(
            Diagnostico.id.label('diagnostico_id'),
            func.row_number().over(
                partition_by=Diagnostico.moto_id,
                order_by=(Diagnostico.fecha.desc(), Diagnostico.id.desc()),
            ).label('posicion'),
        )
        .join(Moto, Diagnostico.moto_id == Moto.id)
        .filter(
            Diagnostico.taller_id == taller_id,
            Moto.taller_id == taller_id,
            Moto.transferida.is_(False),
        )
        .subquery()
    )
    diagnosticos = (
        Diagnostico.query
        .join(recientes, Diagnostico.id == recientes.c.diagnostico_id)
        .filter(recientes.c.posicion == 1)
        .options(joinedload(Diagnostico.moto))
        .all()
    )
    resultados = [serializar_diagnostico(item) for item in diagnosticos]
    resultados.sort(key=lambda item: item['peso_prioridad'], reverse=True)
    return jsonify(resultados)


@scanner_bp.route('/diagnosticos/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_diagnostico(id):
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecánicos pueden eliminar diagnósticos'}), 403
    diagnostico = Diagnostico.query.filter_by(
        id=id, taller_id=taller_actual_id()
    ).first()
    if not diagnostico:
        return jsonify({'error': 'Diagnóstico no encontrado.'}), 404
    registrar_auditoria('diagnostico', diagnostico.id, 'eliminar', antes={
        'moto_id': diagnostico.moto_id, 'codigo_error': diagnostico.codigo_error,
    })
    db.session.delete(diagnostico)
    db.session.commit()
    return jsonify({'mensaje': 'Diagnóstico eliminado con éxito'})


@scanner_bp.route('/mis_diagnosticos', methods=['GET'])
@jwt_required()
def mis_diagnosticos():
    if get_jwt().get('rol') != 'cliente':
        return jsonify({'error': 'Esta vista es solo para clientes'}), 403

    usuario = usuario_actual()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    cliente = Cliente.query.filter_by(
        email=usuario.username, taller_id=usuario.taller_id
    ).first()
    if not cliente:
        return jsonify([])

    consulta = (
        Diagnostico.query
        .filter_by(taller_id=usuario.taller_id)
        .join(Moto)
        .filter(
            Moto.cliente_id == cliente.id,
            Moto.transferida.is_(False),
        )
        .options(joinedload(Diagnostico.moto))
        .order_by(Diagnostico.fecha.desc(), Diagnostico.id.desc())
    )
    return respuesta_paginada(consulta, serializar_diagnostico)
