"""Paginación uniforme para los listados de la API."""
from flask import jsonify, request


LOTE_SIN_PAGINACION = 500


def _serializar(items, serializador, preparar):
    if preparar is not None:
        preparado = preparar(items)
        if callable(preparado):
            serializador = preparado
    return [serializador(item) for item in items]


def respuesta_paginada(
    consulta, serializador, *, por_defecto=50, maximo=200, preparar=None,
):
    """Devuelve una lista si no se piden páginas o un objeto paginado si se piden.

    Se mantiene la compatibilidad con el frontend actual (que espera arreglos)
    y se ofrece paginación explícita mediante ``?page=1&per_page=50``.

    ``preparar`` recibe la lista de elementos ya cargada y puede devolver el
    serializador que se usará para esa página. Sirve para resolver relaciones
    costosas con una sola consulta adicional en lugar de cargar todo el
    historial de cada fila.

    ``?total=0`` omite el ``COUNT(*)`` y devuelve ``total``/``pages`` en
    ``null``; útil para desplazamientos sobre tablas grandes donde el cliente
    solo necesita los elementos.
    """
    pagina = request.args.get('page', type=int)
    por_pagina = request.args.get('per_page', type=int)
    if pagina is None and por_pagina is None:
        items = consulta.limit(LOTE_SIN_PAGINACION).all()
        return jsonify(_serializar(items, serializador, preparar))

    pagina = max(1, pagina or 1)
    por_pagina = max(1, min(por_pagina or por_defecto, maximo))
    calcular_total = request.args.get('total', default='1').strip().lower() not in (
        '0', 'false', 'no',
    )
    total = consulta.order_by(None).count() if calcular_total else None
    items = consulta.offset((pagina - 1) * por_pagina).limit(por_pagina).all()
    paginas = (
        (total + por_pagina - 1) // por_pagina if total is not None else None
    )
    return jsonify({
        'items': _serializar(items, serializador, preparar),
        'page': pagina,
        'per_page': por_pagina,
        'total': total,
        'pages': paginas,
    })
