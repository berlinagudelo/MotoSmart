from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO

from flask import Blueprint, jsonify, request
from flask import send_file
from flask_jwt_extended import get_jwt, jwt_required

from db import db
from modelo.clientes import Cliente
from modelo.factura import Factura
from modelo.moto import Moto
from services.tenencia import taller_actual_id, usuario_actual


facturas_bp = Blueprint('facturas', __name__)
ESTADOS = {'pendiente', 'pagada'}


def es_mecanico():
    return get_jwt().get('rol') == 'mecanico'


def serializar_factura(factura, incluir_cliente=True):
    moto = factura.moto
    resultado = {'id': factura.id, 'numero': factura.numero, 'fecha': factura.fecha.isoformat(),
                 'descripcion': factura.descripcion, 'subtotal': str(factura.subtotal),
                 'iva': str(factura.iva), 'total': str(factura.total), 'estado': factura.estado,
                 'moto': {'id': moto.id, 'placa': moto.placa, 'marca': moto.marca, 'modelo': moto.modelo} if moto else None}
    if incluir_cliente and moto and moto.cliente:
        resultado['cliente'] = {'id': moto.cliente.id, 'nombre': moto.cliente.nombre, 'email': moto.cliente.email}
    return resultado


def validar_datos(data):
    if not isinstance(data, dict):
        return None, 'Datos de factura inválidos.'
    try:
        moto_id = int(data.get('moto_id'))
        fecha = datetime.strptime(str(data.get('fecha', '')), '%Y-%m-%d').date()
        subtotal = Decimal(str(data.get('subtotal')))
        iva = Decimal(str(data.get('iva', 19)))
    except (TypeError, ValueError, InvalidOperation):
        return None, 'Revisa la moto, fecha, subtotal e IVA de la factura.'
    descripcion = str(data.get('descripcion', '')).strip()
    estado = str(data.get('estado', 'pendiente')).strip().lower()
    if not descripcion or len(descripcion) > 500:
        return None, 'Ingresa un detalle de servicio de máximo 500 caracteres.'
    if subtotal < 0 or iva < 0 or iva > 100:
        return None, 'El subtotal y el IVA deben tener valores válidos.'
    moto = Moto.query.filter_by(
        id=moto_id, taller_id=taller_actual_id(), transferida=False
    ).first()
    if not moto:
        return None, 'La moto seleccionada no existe.'
    if estado not in ESTADOS:
        return None, 'Selecciona un estado válido.'
    subtotal = subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    iva = iva.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total = (subtotal * (Decimal('1') + iva / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {'moto_id': moto.id, 'fecha': fecha, 'descripcion': descripcion, 'subtotal': subtotal,
            'iva': iva, 'total': total, 'estado': estado}, None


def factura_permitida(factura):
    if es_mecanico():
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
    return str(valor).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').encode('latin-1', 'replace').decode('latin-1')


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
    pdf.extend(f'trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF'.encode())
    return BytesIO(bytes(pdf))


@facturas_bp.route('/facturas', methods=['GET'])
@jwt_required()
def listar_facturas():
    if not es_mecanico():
        return jsonify({'error': 'Solo mecánicos pueden ver la facturación del taller.'}), 403
    facturas = Factura.query.filter_by(
        taller_id=taller_actual_id()
    ).order_by(Factura.fecha.desc(), Factura.id.desc()).all()
    return jsonify([serializar_factura(factura) for factura in facturas])


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
    facturas = Factura.query.filter_by(
        taller_id=usuario.taller_id
    ).join(Moto).filter(Moto.cliente_id == cliente.id).order_by(
        Factura.fecha.desc(), Factura.id.desc()
    ).all()
    return jsonify([serializar_factura(factura, incluir_cliente=False) for factura in facturas])


@facturas_bp.route('/facturas', methods=['POST'])
@jwt_required()
def crear_factura():
    if not es_mecanico():
        return jsonify({'error': 'Solo mecánicos pueden crear facturas.'}), 403
    datos, error = validar_datos(request.get_json(silent=True))
    if error:
        return jsonify({'error': error}), 400
    factura = Factura(
        numero='PENDIENTE',
        taller_id=taller_actual_id(),
        **datos
    )
    db.session.add(factura)
    db.session.flush()
    factura.numero = f'FAC-{factura.id:06d}'
    db.session.commit()
    return jsonify({'mensaje': 'Factura creada con éxito.', 'factura': serializar_factura(factura)}), 201


@facturas_bp.route('/facturas/<int:factura_id>', methods=['PUT'])
@jwt_required()
def actualizar_factura(factura_id):
    if not es_mecanico():
        return jsonify({'error': 'Solo mecánicos pueden editar facturas.'}), 403
    datos, error = validar_datos(request.get_json(silent=True))
    if error:
        return jsonify({'error': error}), 400
    factura = Factura.query.filter_by(
        id=factura_id, taller_id=taller_actual_id()
    ).first_or_404()
    for campo, valor in datos.items():
        setattr(factura, campo, valor)
    db.session.commit()
    return jsonify({'mensaje': 'Factura actualizada con éxito.', 'factura': serializar_factura(factura)})


@facturas_bp.route('/facturas/<int:factura_id>', methods=['DELETE'])
@jwt_required()
def eliminar_factura(factura_id):
    if not es_mecanico():
        return jsonify({'error': 'Solo mecánicos pueden eliminar facturas.'}), 403
    factura = Factura.query.filter_by(
        id=factura_id, taller_id=taller_actual_id()
    ).first_or_404()
    db.session.delete(factura)
    db.session.commit()
    return jsonify({'mensaje': 'Factura eliminada.'})


@facturas_bp.route('/facturas/<int:factura_id>/pdf', methods=['GET'])
@jwt_required()
def descargar_factura_pdf(factura_id):
    factura = Factura.query.filter_by(
        id=factura_id, taller_id=taller_actual_id()
    ).first_or_404()
    if not factura_permitida(factura):
        return jsonify({'error': 'No tienes permiso para descargar esta factura.'}), 403
    return send_file(generar_pdf_factura(factura), mimetype='application/pdf', as_attachment=True,
                     download_name=f'{factura.numero}.pdf')
