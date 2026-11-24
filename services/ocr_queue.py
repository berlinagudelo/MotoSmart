"""Cola persistente de trabajos OCR sobre la base de datos.

Diseño:
- La petición web guarda la imagen y crea una fila ``pendiente``.
- Uno o varios workers reclaman filas de forma atómica
  (``FOR UPDATE SKIP LOCKED`` en PostgreSQL).
- El resultado se guarda en la misma fila y la imagen temporal se elimina.
- Si un worker muere, el trabajo atascado vuelve a la cola tras el timeout.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app

from db import db
from modelo.diagnostico import Diagnostico
from modelo.moto import Moto
from modelo.trabajo_ocr import TrabajoOCR
from services.ocr_procesamiento import ErrorOCRNoLegible, procesar_imagen
from services.priorizacion import evaluar_prioridad
from services.seguridad import registrar_auditoria


logger = logging.getLogger('motorsmart.ocr')
_hilo_iniciado = False
_hilo_lock = threading.Lock()


def _ahora():
    return datetime.now(timezone.utc)


def directorio_ocr():
    directorio = os.path.abspath(current_app.config['MOTOSMART_OCR_DIR'])
    static = os.path.abspath(current_app.static_folder or '')
    if static and (directorio == static or directorio.startswith(static + os.sep)):
        raise RuntimeError('MOTOSMART_OCR_DIR no puede estar dentro de static/.')
    os.makedirs(directorio, exist_ok=True)
    try:
        os.chmod(directorio, 0o700)
    except OSError:
        pass
    return directorio


def guardar_imagen(archivo, extension):
    """Guarda la imagen con un nombre aleatorio fuera de static/."""
    directorio = directorio_ocr()
    ruta = os.path.join(directorio, f'{uuid.uuid4().hex}{extension}')
    archivo.save(ruta)
    return ruta


def crear_trabajo(moto, usuario, archivo, extension, tamano):
    ruta = guardar_imagen(archivo, extension)
    try:
        trabajo = TrabajoOCR(
            taller_id=moto.taller_id,
            moto_id=moto.id,
            usuario_id=usuario.id if usuario else None,
            estado='pendiente',
            ruta_archivo=ruta,
            nombre_original=(archivo.filename or '')[:255],
            tamano=tamano,
            intentos=0,
            max_intentos=current_app.config.get('MOTOSMART_OCR_MAX_INTENTOS', 3),
        )
        db.session.add(trabajo)
        db.session.commit()
        return trabajo
    except Exception:
        db.session.rollback()
        if os.path.exists(ruta):
            os.remove(ruta)
        raise


def serializar_trabajo(trabajo):
    resultado = None
    if trabajo.resultado_json:
        try:
            resultado = json.loads(trabajo.resultado_json)
        except (TypeError, json.JSONDecodeError):
            resultado = None
    return {
        'id': trabajo.id,
        'estado': trabajo.estado,
        'intentos': trabajo.intentos,
        'max_intentos': trabajo.max_intentos,
        'diagnostico_id': trabajo.diagnostico_id,
        'error': trabajo.error,
        'resultado': resultado,
        'creado_en': trabajo.creado_en.isoformat() if trabajo.creado_en else None,
        'terminado_en': trabajo.terminado_en.isoformat() if trabajo.terminado_en else None,
    }


def _recuperar_atascados():
    timeout = current_app.config.get('MOTOSMART_OCR_TIMEOUT_SEGUNDOS', 600)
    limite = _ahora() - timedelta(seconds=timeout)
    atascados = TrabajoOCR.query.filter(
        TrabajoOCR.estado == 'procesando',
        TrabajoOCR.actualizado_en < limite,
    ).limit(50).all()
    for trabajo in atascados:
        trabajo.intentos = int(trabajo.intentos or 0) + 1
        trabajo.error = 'El worker anterior se interrumpió; el trabajo se reintenta.'
        trabajo.estado = (
            'error' if trabajo.intentos >= trabajo.max_intentos else 'pendiente'
        )
        if trabajo.estado == 'error':
            eliminar_archivo_ocr(trabajo.ruta_archivo)
    if atascados:
        db.session.commit()
        logger.warning('Se recuperaron %s trabajos OCR atascados.', len(atascados))


def reclamar_trabajo():
    """Marca un trabajo como ``procesando`` y devuelve su id."""
    _recuperar_atascados()
    consulta = (
        TrabajoOCR.query
        .filter(TrabajoOCR.estado == 'pendiente')
        .order_by(TrabajoOCR.creado_en.asc(), TrabajoOCR.id.asc())
    )
    es_postgres = db.engine.dialect.name == 'postgresql'
    if es_postgres:
        trabajo = consulta.with_for_update(skip_locked=True).first()
        if not trabajo:
            return None
        trabajo.estado = 'procesando'
        trabajo.iniciado_en = _ahora()
        trabajo.actualizado_en = _ahora()
        trabajo.error = None
        db.session.commit()
        return trabajo.id

    # SQLite u otras bases sin SKIP LOCKED: actualización condicional.
    for candidato in consulta.limit(20).all():
        actualizados = TrabajoOCR.query.filter_by(
            id=candidato.id, estado='pendiente'
        ).update({
            'estado': 'procesando',
            'iniciado_en': _ahora(),
            'actualizado_en': _ahora(),
            'error': None,
        }, synchronize_session=False)
        db.session.commit()
        if actualizados:
            return candidato.id
    return None


def eliminar_archivo_ocr(ruta):
    try:
        if ruta and os.path.exists(ruta):
            os.remove(ruta)
    except OSError:
        logger.warning('No se pudo eliminar la imagen OCR %s', ruta)


def procesar_trabajo(trabajo_id):
    """Procesa un trabajo ya reclamado. Devuelve (id, estado, error)."""
    trabajo = db.session.get(TrabajoOCR, trabajo_id)
    if trabajo is None:
        return None, 'desconocido', 'El trabajo no existe.'
    if trabajo.estado == 'completado':
        return trabajo.id, trabajo.estado, None

    fatal = False
    try:
        if not trabajo.ruta_archivo or not os.path.exists(trabajo.ruta_archivo):
            raise RuntimeError('La imagen del trabajo ya no está disponible.')
        moto = db.session.get(Moto, trabajo.moto_id)
        if (
            moto is None
            or moto.taller_id != trabajo.taller_id
            or bool(moto.transferida)
        ):
            raise RuntimeError('La moto del diagnóstico ya no está disponible en el taller.')

        codigo, descripcion, detalles = procesar_imagen(trabajo.ruta_archivo)
        analisis = evaluar_prioridad(detalles)
        diagnostico = Diagnostico(
            moto_id=moto.id,
            taller_id=trabajo.taller_id,
            codigo_error=codigo,
            descripcion=descripcion,
            detalle_codigos=json.dumps(detalles),
            prioridad=analisis['prioridad'],
            motivo_prioridad=analisis['motivo_prioridad'],
            recomendacion=analisis['recomendacion'],
        )
        db.session.add(diagnostico)
        db.session.flush()
        registrar_auditoria(
            'diagnostico', diagnostico.id, 'crear',
            despues={'moto_id': moto.id, 'codigo_error': codigo, 'origen': 'ocr'},
            usuario_id=trabajo.usuario_id, taller_id=trabajo.taller_id,
        )
        trabajo.estado = 'completado'
        trabajo.diagnostico_id = diagnostico.id
        trabajo.resultado_json = json.dumps({
            'mensaje': 'Diagnóstico guardado',
            'codigo_error': diagnostico.codigo_error,
            'descripcion': diagnostico.descripcion,
            'detalles': detalles,
            'diagnostico_id': diagnostico.id,
            **analisis,
        }, ensure_ascii=False, default=str)
        trabajo.error = None
        trabajo.terminado_en = _ahora()
        trabajo.actualizado_en = _ahora()
        db.session.commit()
        eliminar_archivo_ocr(trabajo.ruta_archivo)
        return trabajo.id, 'completado', None
    except ErrorOCRNoLegible as error:
        fatal = True
        mensaje = str(error)
    except Exception as error:
        logger.exception('Fallo al procesar el trabajo OCR %s', trabajo_id)
        mensaje = str(error)[:2000] or 'Error inesperado al procesar la imagen.'

    db.session.rollback()
    trabajo = db.session.get(TrabajoOCR, trabajo_id)
    if trabajo is None:
        return trabajo_id, 'error', mensaje
    trabajo.intentos = int(trabajo.intentos or 0) + 1
    trabajo.error = mensaje
    trabajo.actualizado_en = _ahora()
    if fatal or trabajo.intentos >= trabajo.max_intentos:
        trabajo.estado = 'error'
        trabajo.terminado_en = _ahora()
        eliminar_archivo_ocr(trabajo.ruta_archivo)
    else:
        trabajo.estado = 'pendiente'
    db.session.commit()
    return trabajo.id, trabajo.estado, mensaje


def ejecutar_worker(intervalo=2.0, max_trabajos=0, una_vez=False):
    """Bucle del worker. Debe ejecutarse con un contexto de aplicación."""
    procesados = 0
    while True:
        trabajo_id = reclamar_trabajo()
        if trabajo_id is None:
            db.session.remove()
            if una_vez or (max_trabajos and procesados >= max_trabajos):
                break
            time.sleep(max(0.5, float(intervalo)))
            continue
        _, estado, error = procesar_trabajo(trabajo_id)
        procesados += 1
        logger.info('Trabajo OCR %s terminó en estado %s%s',
                    trabajo_id, estado, f' ({error})' if error else '')
        db.session.remove()
        if una_vez or (max_trabajos and procesados >= max_trabajos):
            break
    return procesados


def iniciar_trabajador_en_hilo(app, intervalo=2.0):
    """Worker interno para desarrollo/escritorio (un solo proceso)."""
    global _hilo_iniciado
    with _hilo_lock:
        if _hilo_iniciado:
            return None
        _hilo_iniciado = True

    def bucle():
        with app.app_context():
            try:
                ejecutar_worker(intervalo=intervalo)
            except Exception:  # pragma: no cover - salvaguarda del hilo
                logger.exception('El worker OCR interno se detuvo.')

    hilo = threading.Thread(target=bucle, name='motorsmart-ocr', daemon=True)
    hilo.start()
    return hilo


def limpiar_trabajos(dias):
    """Elimina trabajos terminados antiguos y sus imágenes residuales."""
    limite = _ahora() - timedelta(days=max(1, int(dias)))
    antiguos = TrabajoOCR.query.filter(
        TrabajoOCR.estado.in_(('completado', 'error')),
        TrabajoOCR.creado_en < limite,
    ).all()
    for trabajo in antiguos:
        eliminar_archivo_ocr(trabajo.ruta_archivo)
        db.session.delete(trabajo)
    if antiguos:
        db.session.commit()
    return len(antiguos)
