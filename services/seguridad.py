"""Utilidades de seguridad: limitación de peticiones y auditoría."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from functools import wraps

from flask import current_app, has_app_context, has_request_context, jsonify, request
from flask_jwt_extended import get_jwt_identity

from db import db
from modelo.auditoria import Auditoria


logger = logging.getLogger('motorsmart.seguridad')

_registros: dict[str, deque] = {}
_lock = threading.Lock()
_redis_cliente = None
_redis_intentado = False
_redis_error = None

# Ventana deslizante atómica. Devuelve {1, 0} o {0, segundos_para_reintentar}.
_LUA_VENTANA = """
local clave = KEYS[1]
local ahora = tonumber(ARGV[1])
local ventana = tonumber(ARGV[2])
local limite = tonumber(ARGV[3])
local miembro = ARGV[4]
redis.call('ZREMRANGEBYSCORE', clave, '-inf', ahora - ventana)
local usados = redis.call('ZCARD', clave)
if usados >= limite then
  local primero = redis.call('ZRANGE', clave, 0, 0, 'WITHSCORES')
  local reintentar = 1
  if primero[2] then
    reintentar = math.max(1, math.ceil((tonumber(primero[2]) + ventana - ahora) / 1000))
  end
  return {0, reintentar}
end
redis.call('ZADD', clave, ahora, miembro)
redis.call('PEXPIRE', clave, ventana)
return {1, 0}
"""


def _url_redis():
    if has_app_context():
        return current_app.config.get('MOTOSMART_REDIS_URL')
    return os.environ.get('MOTOSMART_REDIS_URL', '').strip() or None


def cliente_redis():
    """Devuelve un cliente Redis compartido o None si no está configurado/caído."""
    global _redis_cliente, _redis_intentado, _redis_error
    url = _url_redis()
    if not url:
        return None
    if _redis_intentado:
        return _redis_cliente
    _redis_intentado = True
    try:
        import redis

        _redis_cliente = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        _redis_cliente.ping()
        logger.info('Rate limiting compartido activo mediante Redis.')
    except Exception as error:  # pragma: no cover - depende del entorno
        _redis_cliente = None
        _redis_error = str(error)
        logger.warning(
            'No se pudo conectar a Redis (%s). El rate limiting quedará por proceso.',
            error,
        )
    return _redis_cliente


def estado_almacen_limites():
    """Resumen para /health sin exponer credenciales."""
    url = _url_redis()
    if not url:
        return {'backend': 'memory', 'compartido': False, 'estado': 'sin_configurar'}
    cliente = cliente_redis()
    if cliente is None:
        return {
            'backend': 'memory', 'compartido': False,
            'estado': 'degradado', 'error': _redis_error,
        }
    try:
        cliente.ping()
        return {'backend': 'redis', 'compartido': True, 'estado': 'ok'}
    except Exception as error:
        return {'backend': 'redis', 'compartido': False, 'estado': 'error', 'error': str(error)}


def _limpiar(ahora, ventana):
    if len(_registros) < 5000:
        return
    for clave in list(_registros):
        cola = _registros[clave]
        while cola and cola[0] <= ahora - ventana:
            cola.popleft()
        if not cola:
            _registros.pop(clave, None)


def _permitir_memoria(clave: str, limite: int, ventana: int):
    ahora = time.monotonic()
    with _lock:
        cola = _registros.setdefault(clave, deque())
        while cola and cola[0] <= ahora - ventana:
            cola.popleft()
        if len(cola) >= limite:
            reintentar = max(1, int(cola[0] + ventana - ahora) + 1)
            return False, reintentar
        cola.append(ahora)
        _limpiar(ahora, ventana)
    return True, 0


def _permitir_redis(cliente, clave: str, limite: int, ventana: int):
    ahora_ms = int(time.time() * 1000)
    miembro = f'{ahora_ms}-{uuid.uuid4().hex}'
    resultado = cliente.eval(
        _LUA_VENTANA, 1, f'motorsmart:rl:{clave}',
        ahora_ms, ventana * 1000, limite, miembro,
    )
    return bool(int(resultado[0])), int(resultado[1])


def permitir_peticion(clave: str, limite: int, ventana: int):
    """Ventana deslizante compartida si Redis está configurado.

    Devuelve (permitido, segundos_para_reintentar). Si Redis falla en caliente,
    se degrada al contador local para no bloquear la operación del taller.
    """
    cliente = cliente_redis()
    if cliente is not None:
        try:
            return _permitir_redis(cliente, clave, limite, ventana)
        except Exception as error:  # pragma: no cover - depende del entorno
            logger.warning('Redis falló durante el rate limiting: %s', error)
    return _permitir_memoria(clave, limite, ventana)


def limitar(limite: int, ventana: int, *, por='ip', nombre=None):
    """Limita peticiones por IP, correo o usuario autenticado.

    La implementación es local al proceso. En despliegues con varios workers se
    debe usar un almacén compartido (Redis) para que el límite sea global.
    """
    def decorador(fn):
        @wraps(fn)
        def envoltura(*args, **kwargs):
            if not current_app.config.get('RATELIMIT_ENABLED', True):
                return fn(*args, **kwargs)
            partes = [request.remote_addr or 'desconocido', nombre or fn.__name__]
            if por == 'email':
                datos = request.get_json(silent=True) or {}
                valor = datos.get('username') or datos.get('email') or ''
                partes.append(str(valor).strip().lower())
            elif por == 'usuario':
                try:
                    partes.append(str(get_jwt_identity() or ''))
                except Exception:
                    pass
            permitido, reintentar = permitir_peticion(':'.join(partes), limite, ventana)
            if not permitido:
                respuesta = jsonify({
                    'error': 'Demasiadas solicitudes. Inténtalo de nuevo más tarde.'
                })
                respuesta.headers['Retry-After'] = str(reintentar)
                return respuesta, 429
            return fn(*args, **kwargs)
        return envoltura
    return decorador


def _json_seguro(valor):
    if valor is None:
        return None
    return json.dumps(valor, ensure_ascii=False, default=str, sort_keys=True)


def registrar_auditoria(entidad, entidad_id, accion, antes=None, despues=None,
                        *, usuario_id=None, taller_id=None):
    """Añade un registro de auditoría a la transacción actual.

    No hace commit: la auditoría debe confirmarse junto con el cambio que
    describe o revertirse con él.
    """
    if usuario_id is None:
        try:
            identidad = get_jwt_identity()
            if identidad is not None:
                usuario_id = int(identidad)
        except Exception:
            usuario_id = None
    if usuario_id is not None and taller_id is None:
        from modelo.usuario import Usuario
        usuario = db.session.get(Usuario, usuario_id)
        taller_id = usuario.taller_id if usuario else None
    ip = None
    if has_request_context():
        ip = (request.remote_addr or '')[:45] or None
        if taller_id is None:
            try:
                taller_id = int((request.get_json(silent=True) or {}).get('taller_id'))
            except Exception:
                taller_id = None
    db.session.add(Auditoria(
        taller_id=taller_id,
        usuario_id=usuario_id,
        entidad=entidad,
        entidad_id=entidad_id,
        accion=accion,
        datos_antes=_json_seguro(antes),
        datos_despues=_json_seguro(despues),
        ip=ip,
    ))
