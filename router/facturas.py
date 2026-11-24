from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from db import db
from modelo.clientes import Cliente
from modelo.factura import Factura
from modelo.moto import Moto
from modelo.taller import Taller
from services.paginacion import respuesta_paginada
from services.seguridad import registrar_auditoria
from services.tenencia import es_titular, taller_actual_id, usuario_actual
from services.validacion import cuerpo_json, decimal_campo, entero, fecha_campo, texto


facturas_bp = Blueprint('facturas', __name__)
ESTADOS = {'pendiente', 'pagada'}
MAX_MONTO = Decimal('9999999999.99')


def es_mecanico():
    return get_jwt().get('rol') == 'mecanico'


def _puede_gestionar_facturas():
    return es_mecanico() or get_jwt().get('rol') == 'admin'


def _puede_editar_facturas():
    return get_jwt().get('rol') == 'admin' or es_titular(usuario_actual())


def serializar_factura(factura, incluir_cliente=True):
    moto = factura.moto
    resultado = {
        'id': factura.id,
        'numero': factura.numero,
        'fecha': factura.fecha.isoformat(),
        'descripcion': factura.descripcion,
        'subtotal': str(factura.subtotal),
        'iva': str(factura.iva),
        'total': str(factura.total),
        'estado': factura.estado,
        'moto': {
            'id': moto.id, 'placa': moto.placa, 'marca': moto.marca, 'modelo': moto.modelo,
        } if moto else None,
    }
    if incluir_cliente and moto and moto.cliente:
        resultado['cliente'] = {
            'id': moto.cliente.id,
            'nombre': moto.cliente.nombre,
            'email': moto.cliente.email,
        }
    return resultado


def validar_datos(data, *, permitir_anulada=False):
    moto_id = entero(data, 'moto_id', minimo=1)
    fecha = fecha_campo(data, 'fecha')
    subtotal = decimal_campo(data, 'subtotal', minimo=Decimal('0'), maximo=MAX_MONTO)
    iva = decimal_campo(
        data, 'iva', minimo=Decimal('0'), maximo=Decimal('100'), default=Decimal('19')
    )
    descripcion = texto(data, 'descripcion', maximo=500)
    estado = texto(data, 'estado', requerido=False, default='pendiente', maximo=15, lower=True)
    estados_validos = ESTADOS | ({'anulada'} if permitir_anulada else set())
    if estado not in estados_validos:
        raise ValueError('Selecciona un estado válido.')
    moto = Moto.query.filter_by(
        id=moto_id, taller_id=taller_actual_id(), transferida=False
    ).first()
    if not moto:
        raise ValueError('La moto seleccionada no existe.')

    subtotal = subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    iva = iva.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total = (subtotal * (Decimal('1') + iva / Decimal('100'))).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    if total > MAX_MONTO:
        raise ValueError('El total de la factura supera el máximo permitido.')
    return {
        'moto_id': moto.id,
        'fecha': fecha,
        'descripcion': descripcion,
        'subtotal': subtotal,
        'iva': iva,
        'total': total,
        'estado': estado,
    }


def factura_permitida(factura):
    if _puede_gestionar_facturas():
        return True
    if get_jwt().get('rol') != 'cliente':
        return False
    usuario = usuario_actual()
    return bool(
        usuario
        and factura.taller_id == usuario.taller_id
        and factura.moto
        and factura.moto.cliente
        and factura.moto.cliente.email == usuario.username
        and factura.moto.cliente.taller_id == usuario.taller_id
    )


def texto_pdf(valor):
    return (
        str(valor)
        .replace('\\', '\\\\')
        .replace('(', '\\(')
        .replace(')', '\\)')
        .encode('latin-1', 'replace')
        .decode('latin-1')
    )


def generar_pdf_factura(factura):
    moto = factura.moto
    cliente = moto.cliente if moto else None
    lineas = [
        'MotoSmart - Factura de servicio',
        f'Factura: {factura.numero}',
        f'Fecha: {factura.fecha.isoformat()}',
        f'Cliente: {cliente.nombre if cliente else "-"}',
        f'Moto: {moto.marca} {moto.modelo} - {moto.placa}' if moto else 'Moto: -',
        f'Servicio: {factura.descripcion}',
        f'Subtotal: COP {factura.subtotal}',
        f'IVA: {factura.iva}%',
        f'Total: COP {factura.total}',
        f'Estado: {factura.estado.capitalize()}',
    ]
    contenido = ['BT', '/F1 12 Tf', '50 760 Td']
    for indice, linea in enumerate(lineas):
        if indice:
            contenido.append('0 -24 Td')
        contenido.append(f'({texto_pdf(linea)}) Tj')
    contenido.append('ET')
    stream = '\n'.join(contenido).encode('latin-1', 'replace')
    objetos = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
    ]
    pdf = bytearray(b'%PDF-1.4\n')
    posiciones = [0]
    for indice, objeto in enumerate(objetos, start=1):
        posiciones.append(len(pdf))
        pdf.extend(f'{indice} 0 obj\n'.encode())
        pdf.extend(objeto)
        pdf.extend(b'\nendobj\n')
    inicio_xref = len(pdf)
    pdf.extend(f'xref\n0 {len(objetos) + 1}\n'.encode())
    pdf.extend(b'0000000000 65535 f \n')
    for posicion in posiciones[1:]:
        pdf.extend(f'{posicion:010d} 00000 n \n'.encode())
    pdf.extend(
        f'trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF'.encode()
    )
    return BytesIO(bytes(pdf))


def _consulta_facturas(taller_id):
    return (
        Factura.query
        .filter_by(taller_id=taller_id)
        .options(joinedload(Factura.moto).joinedload(Moto.cliente))
        .order_by(Factura.fecha.desc(), Factura.id.desc())
    )


@facturas_bp.route('/facturas', methods=['GET'])
@jwt_required()
def listar_facturas():
    if not _puede_gestionar_facturas():
        return jsonify({'error': 'Solo mecánicos pueden ver la facturación del taller.'}), 403
    return respuesta_paginada(
        _consulta_facturas(taller_actual_id()), serializar_factura
    )


@facturas_bp.route('/mis_facturas', methods=['GET'])
@jwt_required()
def listar_mis_facturas():
    if get_jwt().get('rol') != 'cliente':
        return jsonify({'error': 'Esta vista es solo para clientes.'}), 403
    usuario = usuario_actual()
    cliente = Cliente.query.filter_by(
        email=usuario.username, taller_id=usuario.taller_id
    ).first() if usuario else None
    if not cliente:
        return jsonify([])
    consulta = (
        Factura.query
        .filter_by(taller_id=usuario.taller_id)
        .join(Moto)
        .filter(Moto.cliente_id == cliente.id)
        .options(joinedload(Factura.moto).joinedload(Moto.cliente))
        .order_by(Factura.fecha.desc(), Factura.id.desc())
    )
    return respuesta_paginada(
        consulta, lambda factura: serializar_factura(factura, incluir_cliente=False)
    )


@facturas_bp.route('/facturas/<int:factura_id>', methods=['GET'])
@jwt_required()
def obtener_factura(factura_id):
    factura = Factura.query.filter_by(
        id=factura_id, taller_id=taller_actual_id()
    ).first()
    if not factura:
        return jsonify({'error': 'Factura no encontrada.'}), 404
    if not factura_permitida(factura):
        return jsonify({'error': 'No tienes permiso para consultar esta factura.'}), 403
    return jsonify(serializar_factura(factura)), 200


@facturas_bp.route('/facturas', methods=['POST'])
@jwt_required()
def crear_factura():
    if not _puede_gestionar_facturas():
        return jsonify({'error': 'Solo mecánicos pueden crear facturas.'}), 403
    try:
        datos = validar_datos(cuerpo_json())
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    taller_id = taller_actual_id()
    clave = request.headers.get('Idempotency-Key', '').strip()[:64] or None
    if clave:
        existente = Factura.query.filter_by(
            taller_id=taller_id, clave_idempotencia=clave
        ).first()
        if existente:
            return jsonify({
                'mensaje': 'La factura ya fue creada con esta clave de idempotencia.',
                'factura': serializar_factura(existente),
            }), 200

    # Bloquea la fila del taller para asignar una secuencia por taller sin
    # colisiones entre peticiones concurrentes.
    db.session.execute(
        db.select(Taller).where(Taller.id == taller_id).with_for_update()
    ).scalar_one_or_none()
    ultima = db.session.query(func.max(Factura.secuencia)).filter_by(
        taller_id=taller_id
    ).scalar() or 0
    secuencia = int(ultima) + 1
    factura = Factura(
        numero=f'FAC-{secuencia:06d}',
        secuencia=secuencia,
        taller_id=taller_id,
        clave_idempotencia=clave,
        **datos,
    )
    db.session.add(factura)
    try:
        db.session.flush()
        registrar_auditoria('factura', factura.id, 'crear', despues=serializar_factura(factura))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return jsonify({
        'mensaje': 'Factura creada con éxito.',
        'factura': serializar_factura(factura),
    }), 201


@facturas_bp.route('/facturas/<int:factura_id>', methods=['PUT', 'PATCH'])
@jwt_required()
def actualizar_factura(factura_id):
    if not _puede_gestionar_facturas():
        return jsonify({'error': 'Solo mecánicos pueden editar facturas.'}), 403
    if not _puede_editar_facturas():
        return jsonify({
            'error': 'Solo el titular del taller puede modificar facturas emitidas.'
        }), 403
    factura = Factura.query.filter_by(
        id=factura_id, taller_id=taller_actual_id()
    ).first()
    if not factura:
        return jsonify({'error': 'Factura no encontrada.'}), 404
    if factura.estado == 'pagada':
        return jsonify({
            'error': 'Una factura pagada es inmutable. Emite una nota de crédito o una nueva factura.'
        }), 409
    if factura.estado == 'anulada':
        return jsonify({'error': 'Una factura anulada no se puede modificar.'}), 409
    try:
        datos = validar_datos(cuerpo_json())
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    antes = serializar_factura(factura)
    for campo, valor in datos.items():
        setattr(factura, campo, valor)
    try:
        registrar_auditoria(
            'factura', factura.id, 'actualizar',
            antes=antes, despues=serializar_factura(factura),
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return jsonify({
        'mensaje': 'Factura actualizada con éxito.',
        'factura': serializar_factura(factura),
    })


@facturas_bp.route('/facturas/<int:factura_id>', methods=['DELETE'])
@jwt_required()
def eliminar_factura(factura_id):
    if not _puede_gestionar_facturas():
        return jsonify({'error': 'Solo mecánicos pueden anular facturas.'}), 403
    if not _puede_editar_facturas():
        return jsonify({
            'error': 'Solo el titular del taller puede anular facturas.'
        }), 403
    factura = Factura.query.filter_by(
        id=factura_id, taller_id=taller_actual_id()
    ).first()
    if not factura:
        return jsonify({'error': 'Factura no encontrada.'}), 404
    if factura.estado == 'pagada':
        return jsonify({
            'error': 'Una factura pagada no se puede anular. Emite una nota de crédito.'
        }), 409
    if factura.estado == 'anulada':
        return jsonify({'error': 'La factura ya está anulada.'}), 409
    antes = serializar_factura(factura)
    factura.estado = 'anulada'
    registrar_auditoria(
        'factura', factura.id, 'anular',
        antes=antes, despues=serializar_factura(factura),
    )
    db.session.commit()
    return jsonify({'mensaje': 'Factura anulada. El registro se conserva para auditoría.'})


@facturas_bp.route('/facturas/<int:factura_id>/pdf', methods=['GET'])
@jwt_required()
def descargar_factura_pdf(factura_id):
    factura = Factura.query.filter_by(
        id=factura_id, taller_id=taller_actual_id()
    ).first()
    if not factura:
        return jsonify({'error': 'Factura no encontrada.'}), 404
    if not factura_permitida(factura):
        return jsonify({'error': 'No tienes permiso para descargar esta factura.'}), 403
    return send_file(
        generar_pdf_factura(factura),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{factura.numero}.pdf',
    )
