"""Derechos sobre datos personales y política de retención.

- Exportación completa de la cuenta en JSON.
- Anonimización (derecho al olvido) conservando únicamente los registros
  contables que la ley exige mantener.
- Limpieza programada de tokens vencidos, trabajos OCR y auditoría antigua.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func

from db import db
from modelo.auditoria import Auditoria
from modelo.citas import Cita
from modelo.clientes import Cliente
from modelo.diagnostico import Diagnostico
from modelo.factura import Factura
from modelo.moto import Moto
from modelo.orden_servicio import OrdenServicio
from modelo.registro_pendiente import RegistroPendiente
from modelo.trabajo_ocr import TrabajoOCR
from modelo.taller import Taller
from modelo.usuario import Usuario
from services.ocr_queue import eliminar_archivo_ocr
from services.seguridad import registrar_auditoria


class ErrorPrivacidad(Exception):
    def __init__(self, mensaje, status=409):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status = status


def _valor(valor):
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return valor


def _con_zona(valor):
    if valor is None:
        return None
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor


def _serializar_moto(moto):
    return {
        'id': moto.id,
        'placa': moto.placa,
        'marca': moto.marca,
        'modelo': moto.modelo,
        'tipo_tecnologia': moto.tipo_tecnologia,
        'transferida': bool(moto.transferida),
    }


def exportar_datos(usuario):
    """Devuelve todos los datos personales y operativos de la cuenta."""
    taller = db.session.get(Taller, usuario.taller_id)
    clientes = Cliente.query.filter_by(email=usuario.username).all()
    cliente_ids = [cliente.id for cliente in clientes]
    motos = (
        Moto.query.filter(Moto.cliente_id.in_(cliente_ids)).all()
        if cliente_ids else []
    )
    moto_ids = [moto.id for moto in motos]

    citas = Cita.query.filter(Cita.moto_id.in_(moto_ids)).all() if moto_ids else []
    diagnosticos = (
        Diagnostico.query.filter(Diagnostico.moto_id.in_(moto_ids)).all()
        if moto_ids else []
    )
    ordenes = (
        OrdenServicio.query.filter(OrdenServicio.moto_id.in_(moto_ids)).all()
        if moto_ids else []
    )
    facturas = (
        Factura.query.filter(Factura.moto_id.in_(moto_ids)).all()
        if moto_ids else []
    )
    auditoria = (
        Auditoria.query
        .filter(Auditoria.usuario_id == usuario.id)
        .order_by(Auditoria.creada_en.asc())
        .all()
    )

    return {
        'generado_en': datetime.now(timezone.utc).isoformat(),
        'aviso': (
            'Este archivo contiene datos personales. Guárdalo en un lugar seguro '
            'y elimínalo cuando ya no lo necesites.'
        ),
        'cuenta': {
            'email': usuario.username,
            'nombre': usuario.nombre,
            'rol': usuario.rol,
            'taller_id': usuario.taller_id,
            'taller': taller.nombre if taller else None,
            'email_verificado': bool(usuario.email_verificado),
            'activo': bool(usuario.activo),
        },
        'perfil_cliente': [
            {
                'id': cliente.id, 'nombre': cliente.nombre, 'email': cliente.email,
                'telefono': cliente.telefono, 'taller_id': cliente.taller_id,
            }
            for cliente in clientes
        ],
        'motos': [_serializar_moto(moto) for moto in motos],
        'citas': [
            {
                'id': cita.id, 'moto_id': cita.moto_id,
                'fecha': _valor(cita.fecha), 'descripcion': cita.descripcion,
            }
            for cita in citas
        ],
        'diagnosticos': [
            {
                'id': item.id, 'moto_id': item.moto_id,
                'codigo_error': item.codigo_error, 'descripcion': item.descripcion,
                'prioridad': item.prioridad, 'recomendacion': item.recomendacion,
                'fecha': _valor(item.fecha),
            }
            for item in diagnosticos
        ],
        'ordenes_servicio': [
            {
                'id': orden.id, 'numero': orden.numero, 'moto_id': orden.moto_id,
                'descripcion': orden.descripcion, 'estado': orden.estado,
                'creada_en': _valor(orden.creada_en),
                'actualizada_en': _valor(orden.actualizada_en),
                'repuestos': [
                    {'nombre': repuesto.item.nombre, 'cantidad': repuesto.cantidad}
                    for repuesto in orden.repuestos
                ],
            }
            for orden in ordenes
        ],
        'facturas': [
            {
                'id': factura.id, 'numero': factura.numero, 'fecha': _valor(factura.fecha),
                'descripcion': factura.descripcion,
                'subtotal': _valor(factura.subtotal), 'iva': _valor(factura.iva),
                'total': _valor(factura.total), 'estado': factura.estado,
            }
            for factura in facturas
        ],
        'actividad_auditada': [
            {
                'entidad': item.entidad, 'entidad_id': item.entidad_id,
                'accion': item.accion, 'creada_en': _valor(item.creada_en),
                'ip': item.ip,
            }
            for item in auditoria
        ],
    }


def anonimizar_usuario(usuario, *, motivo, actor_id=None, forzar=False, taller_id=None):
    """Anonimiza la cuenta y sus datos de contacto.

    No elimina facturas ni órdenes: son registros contables/operativos que se
    conservan vinculados a un cliente sin datos personales. Los diagnósticos y
    el historial del vehículo se mantienen, pero la placa se anonimiza.

    El alcance por defecto depende del rol:

    - ``cliente``: todas las fichas con su correo (sus datos en cualquier taller,
      incluido uno anterior tras una mudanza).
    - personal del taller (``mecanico``/``admin``): solo su taller. Evita que la
      cuenta de un empleado pueda alterar fichas de clientes de otro taller que
      compartan el mismo correo por error. Un administrador puede indicar
      ``taller_id`` de forma explícita.
    """
    if usuario is None:
        raise ErrorPrivacidad('La cuenta no existe.', 404)
    es_titular = usuario.rol == 'mecanico' and usuario.creado_por_id is None
    if es_titular and not forzar:
        raise ErrorPrivacidad(
            'La cuenta titular no puede eliminarse mientras sea responsable del taller. '
            'Transfiere la titularidad o solicita la anonimización administrativa.'
        )

    email_original = usuario.username
    consulta = Cliente.query.filter_by(email=email_original)
    if usuario.rol != 'cliente':
        alcance = usuario.taller_id if taller_id is None else taller_id
        consulta = consulta.filter(Cliente.taller_id == alcance)
    elif taller_id is not None:
        consulta = consulta.filter(Cliente.taller_id == taller_id)
    clientes = consulta.all()
    hoy = date.today()
    citas_eliminadas = 0
    motos_anonimizadas = 0
    motos_ids = []
    for cliente in clientes:
        for moto in Moto.query.filter_by(cliente_id=cliente.id).all():
            motos_ids.append(moto.id)
            citas_futuras = Cita.query.filter(
                Cita.moto_id == moto.id, Cita.fecha >= hoy
            ).all()
            citas_eliminadas += len(citas_futuras)
            for cita in citas_futuras:
                db.session.delete(cita)
            moto.placa = f'ANON-{moto.id:09d}'
            moto.transferida = True
            motos_anonimizadas += 1
        cliente.nombre = 'Cliente eliminado'
        cliente.email = f'anon-{cliente.id}-{uuid.uuid4().hex[:8]}@invalid.motosmart'
        cliente.telefono = None

    # Los trabajos OCR contienen la ruta a la imagen original: se eliminan las
    # imágenes del cliente y, si es personal, las que él mismo subió.
    trabajos = []
    if motos_ids:
        trabajos.extend(
            TrabajoOCR.query.filter(TrabajoOCR.moto_id.in_(motos_ids)).all()
        )
    trabajos.extend(
        TrabajoOCR.query.filter(TrabajoOCR.usuario_id == usuario.id).all()
    )
    trabajos_unicos = {trabajo.id: trabajo for trabajo in trabajos}
    for trabajo in trabajos_unicos.values():
        eliminar_archivo_ocr(trabajo.ruta_archivo)
        db.session.delete(trabajo)

    RegistroPendiente.query.filter(
        (RegistroPendiente.email == email_original)
        | (RegistroPendiente.usuario_id == usuario.id)
    ).delete(synchronize_session=False)

    usuario.username = f'eliminado-{usuario.id}-{uuid.uuid4().hex[:12]}@invalid.motosmart'
    usuario.nombre = 'Cuenta eliminada'
    usuario.password_hash = uuid.uuid4().hex * 4
    usuario.activo = False
    usuario.email_verificado = False
    usuario.token_version = int(usuario.token_version or 0) + 1

    registrar_auditoria(
        'usuario', usuario.id, 'anonimizar_cuenta',
        despues={
            'motivo': motivo,
            'clientes_anonimizados': len(clientes),
            'motos_anonimizadas': motos_anonimizadas,
            'citas_eliminadas': citas_eliminadas,
            'trabajos_ocr_eliminados': len(trabajos_unicos),
            'alcance_taller': taller_id,
        },
        usuario_id=actor_id if actor_id is not None else usuario.id,
        taller_id=usuario.taller_id,
    )
    return {
        'email_original': email_original,
        'clientes_anonimizados': len(clientes),
        'motos_anonimizadas': motos_anonimizadas,
        'citas_eliminadas': citas_eliminadas,
        'trabajos_ocr_eliminados': len(trabajos_unicos),
    }


def _eliminar_masivo_por_lotes(modelo, condicion, tamano):
    """Borra por identificadores en lotes y confirma cada lote."""
    total = 0
    while True:
        ids = [
            identificador
            for (identificador,) in (
                db.session.query(modelo.id)
                .filter(condicion)
                .limit(tamano)
                .all()
            )
        ]
        if not ids:
            break
        db.session.query(modelo).filter(modelo.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.session.commit()
        total += len(ids)
    return total


def _eliminar_objetos_por_lotes(consulta, tamano, al_eliminar=None):
    """Borra objetos por lotes, ejecutando un gancho antes de cada borrado."""
    total = 0
    while True:
        items = consulta.limit(tamano).all()
        if not items:
            break
        for item in items:
            if al_eliminar is not None:
                al_eliminar(item)
            db.session.delete(item)
        db.session.commit()
        total += len(items)
    return total


def aplicar_retencion(*, dias_auditoria=None, dias_ocr=None, dry_run=False):
    """Aplica la política de retención configurada.

    No borra facturas pagadas ni órdenes entregadas. Los tokens de verificación
    vencidos, los trabajos OCR terminados y la auditoría antigua se eliminan
    por lotes (``MOTOSMART_RETENCION_LOTE``) para no mantener transacciones
    largas ni bloquear la tabla completa.
    """
    from flask import current_app

    dias_auditoria = dias_auditoria or current_app.config.get(
        'MOTOSMART_RETENCION_AUDITORIA_DIAS', 730
    )
    dias_ocr = dias_ocr or current_app.config.get('MOTOSMART_RETENCION_OCR_DIAS', 90)
    tamano_lote = max(100, int(current_app.config.get('MOTOSMART_RETENCION_LOTE', 5000)))
    ahora = datetime.now(timezone.utc)
    resumen = {}

    condicion_pendientes = (
        RegistroPendiente.expires_at <= int(ahora.timestamp())
    )
    if dry_run:
        resumen['registros_pendientes'] = (
            db.session.query(RegistroPendiente.id)
            .filter(condicion_pendientes)
            .count()
        )
    else:
        resumen['registros_pendientes'] = _eliminar_masivo_por_lotes(
            RegistroPendiente, condicion_pendientes, tamano_lote
        )

    limite_ocr = ahora - timedelta(days=max(1, int(dias_ocr)))
    consulta_ocr = TrabajoOCR.query.filter(
        TrabajoOCR.estado.in_(('completado', 'error')),
        TrabajoOCR.creado_en < limite_ocr,
    )
    if dry_run:
        resumen['trabajos_ocr'] = consulta_ocr.count()
    else:
        resumen['trabajos_ocr'] = _eliminar_objetos_por_lotes(
            consulta_ocr,
            tamano_lote,
            lambda trabajo: eliminar_archivo_ocr(trabajo.ruta_archivo),
        )

    limite_auditoria = ahora - timedelta(days=max(30, int(dias_auditoria)))
    condicion_auditoria = Auditoria.creada_en < limite_auditoria
    if dry_run:
        resumen['auditoria'] = (
            db.session.query(Auditoria.id).filter(condicion_auditoria).count()
        )
    else:
        resumen['auditoria'] = _eliminar_masivo_por_lotes(
            Auditoria, condicion_auditoria, tamano_lote
        )

    # Cuentas desactivadas sin actividad reciente. Se anonimizan, no se borran,
    # para no romper facturas ni órdenes que deben conservarse.
    dias_cuentas = current_app.config.get('MOTOSMART_RETENCION_CUENTAS_DIAS', 365)
    limite_cuentas = ahora - timedelta(days=max(30, int(dias_cuentas)))
    ultima_actividad = dict(
        db.session.query(
            Auditoria.usuario_id, func.max(Auditoria.creada_en)
        ).group_by(Auditoria.usuario_id).all()
    )
    inactivas = Usuario.query.filter(
        Usuario.activo.is_(False),
        ~Usuario.username.like('eliminado-%'),
    ).all()
    a_anonimizar = [
        usuario for usuario in inactivas
        if _con_zona(ultima_actividad.get(usuario.id)) is not None
        and _con_zona(ultima_actividad[usuario.id]) < limite_cuentas
    ]
    resumen['cuentas_inactivas'] = len(a_anonimizar)
    if not dry_run:
        for usuario in a_anonimizar:
            anonimizar_usuario(
                usuario, motivo='retencion', actor_id=None, forzar=True,
            )
            db.session.commit()

    if dry_run:
        db.session.rollback()
    return resumen


def exportar_json(usuario, ruta):
    datos = exportar_datos(usuario)
    with open(ruta, 'w', encoding='utf-8') as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2, default=str)
    return ruta
