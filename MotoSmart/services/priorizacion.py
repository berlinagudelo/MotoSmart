"""Motor explicable de priorizacion para diagnosticos de motos."""

PESO_PRIORIDAD = {
    'CRITICA': 4,
    'ALTA': 3,
    'MEDIA': 2,
    'BAJA': 1,
}

CODIGOS_CRITICOS = {
    'P0300': 'Hay fallos de encendido que pueden afectar la operacion del motor.',
    'P0335': 'El sensor de ciguenal puede impedir o afectar el funcionamiento del motor.',
}
CODIGOS_ALTOS = {
    'P0105': 'La lectura de temperatura del motor requiere revision pronta.',
    'P0115': 'La lectura de temperatura del motor requiere revision pronta.',
    'P0120': 'El control del acelerador presenta una lectura anomala.',
    'P0130': 'El sensor de oxigeno puede afectar la mezcla de combustible.',
    'P0171': 'Se detecto una mezcla pobre que puede afectar el motor.',
    'P0351': 'El sistema de encendido requiere revision pronta.',
    'P0562': 'El sistema electrico registra voltaje bajo.',
    'P0700': 'El sistema de transmision reporta una falla.',
}
CODIGOS_MEDIOS = {
    'P0100': 'El sensor de flujo de aire requiere diagnostico.',
    'P0420': 'El sistema de emisiones requiere revision.',
    'P0500': 'El sensor de velocidad requiere revision.',
    'P0600': 'Hay una falla de comunicacion entre modulos.',
}


def evaluar_prioridad(detalles):
    """Devuelve una prioridad, su justificacion y una recomendacion accionable."""
    mejor_nivel = 'BAJA'
    motivos = []

    for detalle in detalles or []:
        codigo = str(detalle.get('codigo', '')).upper()
        if codigo in CODIGOS_CRITICOS or codigo.startswith('C0'):
            nivel = 'CRITICA'
            motivo = CODIGOS_CRITICOS.get(codigo, 'El codigo corresponde a un sistema de chasis o seguridad.')
        elif codigo in CODIGOS_ALTOS or codigo.startswith('U'):
            nivel = 'ALTA'
            motivo = CODIGOS_ALTOS.get(codigo, 'Hay una falla de comunicacion que requiere revision pronta.')
        elif codigo in CODIGOS_MEDIOS or codigo.startswith('P'):
            nivel = 'MEDIA'
            motivo = CODIGOS_MEDIOS.get(codigo, 'El codigo requiere diagnostico en el taller.')
        else:
            nivel = 'BAJA'
            motivo = 'No se detecto un codigo de riesgo alto en la lectura.'

        if PESO_PRIORIDAD[nivel] > PESO_PRIORIDAD[mejor_nivel]:
            mejor_nivel = nivel
        if motivo not in motivos:
            motivos.append(motivo)

    recomendaciones = {
        'CRITICA': 'Priorizar atencion inmediata. Recomendar no usar la moto hasta revisarla.',
        'ALTA': 'Agendar revision prioritaria en las proximas 24 horas.',
        'MEDIA': 'Agendar una revision de taller en los proximos dias.',
        'BAJA': 'Programar revision preventiva cuando sea conveniente.',
    }
    return {
        'prioridad': mejor_nivel,
        'peso_prioridad': PESO_PRIORIDAD[mejor_nivel],
        'motivo_prioridad': ' '.join(motivos) or 'No hay suficientes datos para elevar la prioridad.',
        'recomendacion': recomendaciones[mejor_nivel],
    }
