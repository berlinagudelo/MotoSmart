import json

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from db import db
from modelo.diagnostico import Diagnostico
from modelo.moto import Moto


revision_mecanica_bp = Blueprint('revision_mecanica', __name__)
PRIORIDADES = ('BAJA', 'MEDIA', 'ALTA')


@revision_mecanica_bp.route('/revisiones-mecanicas', methods=['POST'])
@jwt_required()
def crear_revision_mecanica():
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecanicos pueden registrar revisiones'}), 403

    data = request.get_json() or {}
    moto = Moto.query.get(data.get('moto_id'))
    if not moto:
        return jsonify({'error': 'La moto seleccionada no existe'}), 404
    if moto.tipo_tecnologia != 'no_electronica':
        return jsonify({'error': 'Esta revision es exclusiva para motos no electronicas'}), 400

    hallazgos = (data.get('hallazgos') or '').strip()
    diagnostico_final = (data.get('diagnostico') or '').strip()
    recomendacion = (data.get('recomendacion') or '').strip()
    prioridad = (data.get('prioridad') or 'MEDIA').upper()
    if not hallazgos or not diagnostico_final:
        return jsonify({'error': 'Registra los problemas encontrados y el diagnostico'}), 400
    if prioridad not in PRIORIDADES:
        return jsonify({'error': 'La prioridad seleccionada no es valida'}), 400

    detalles = [
        {'codigo': 'HALLAZGOS', 'descripcion': hallazgos},
        {'codigo': 'DIAGNOSTICO MECANICO', 'descripcion': diagnostico_final}
    ]
    revision = Diagnostico(
        moto_id=moto.id,
        codigo_error='REVISION MECANICA',
        descripcion=diagnostico_final,
        detalle_codigos=json.dumps(detalles),
        prioridad=prioridad,
        motivo_prioridad=f'Revision mecanica: {hallazgos}',
        recomendacion=recomendacion or 'Pendiente de recomendacion del mecanico.'
    )
    db.session.add(revision)
    db.session.commit()
    return jsonify({'mensaje': 'Revision mecanica guardada', 'id': revision.id}), 201
