import json

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt, jwt_required

from db import db
from modelo.diagnostico import Diagnostico
from modelo.moto import Moto
from services.seguridad import registrar_auditoria
from services.tenencia import taller_actual_id
from services.validacion import cuerpo_json, entero, texto


revision_mecanica_bp = Blueprint('revision_mecanica', __name__)
PRIORIDADES = ('BAJA', 'MEDIA', 'ALTA')


@revision_mecanica_bp.route('/revisiones-mecanicas', methods=['POST'])
@jwt_required()
def crear_revision_mecanica():
    if get_jwt().get('rol') != 'mecanico':
        return jsonify({'error': 'Solo mecánicos pueden registrar revisiones'}), 403

    data = cuerpo_json()
    taller_id = taller_actual_id()
    moto_id = entero(data, 'moto_id', minimo=1)
    moto = Moto.query.filter_by(
        id=moto_id, taller_id=taller_id, transferida=False
    ).first()
    if not moto:
        return jsonify({'error': 'La moto seleccionada no existe'}), 404
    if moto.tipo_tecnologia != 'no_electronica':
        return jsonify({'error': 'Esta revisión es exclusiva para motos no electrónicas'}), 400

    hallazgos = texto(data, 'hallazgos', maximo=2000)
    diagnostico_final = texto(data, 'diagnostico', maximo=2000)
    recomendacion = texto(
        data, 'recomendacion', requerido=False, default='', maximo=2000,
        permitir_vacio=True,
    )
    prioridad = texto(
        data, 'prioridad', requerido=False, default='MEDIA', maximo=20, upper=True
    )
    if prioridad not in PRIORIDADES:
        return jsonify({'error': 'La prioridad seleccionada no es válida'}), 400

    detalles = [
        {'codigo': 'HALLAZGOS', 'descripcion': hallazgos},
        {'codigo': 'DIAGNOSTICO MECANICO', 'descripcion': diagnostico_final},
    ]
    revision = Diagnostico(
        moto_id=moto.id,
        taller_id=taller_id,
        codigo_error='REVISION MECANICA',
        descripcion=diagnostico_final,
        detalle_codigos=json.dumps(detalles),
        prioridad=prioridad,
        motivo_prioridad=f'Revisión mecánica: {hallazgos}',
        recomendacion=recomendacion or 'Pendiente de recomendación del mecánico.',
    )
    db.session.add(revision)
    db.session.flush()
    registrar_auditoria('diagnostico', revision.id, 'revision_mecanica', despues={
        'moto_id': moto.id, 'prioridad': prioridad,
    })
    db.session.commit()
    return jsonify({'mensaje': 'Revisión mecánica guardada', 'id': revision.id}), 201
