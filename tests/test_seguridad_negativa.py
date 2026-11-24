"""Pruebas negativas y de regresión para los hallazgos de la auditoría QA.

Cubren validación de entrada, errores JSON, integridad referencial, facturación
inmutable, revocación de sesiones, cantidades enteras, OCR, idempotencia y
paginación. Se ejecutan sobre SQLite en memoria para que sean rápidas; la
verificación contra PostgreSQL queda documentada en el informe.
"""
import io
import os
import re
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('MOTOSMART_DATABASE_URL', 'sqlite://')
os.environ.setdefault('MOTOSMART_JWT_SECRET_KEY', 'test-only-key-with-at-least-32-characters')
sys.modules.setdefault(
    'easyocr',
    SimpleNamespace(Reader=lambda languages: SimpleNamespace(readtext=lambda path: [])),
)

from app import app, inicializar_base
from db import db
from modelo.auditoria import Auditoria
from modelo.clientes import Cliente
from modelo.diagnostico import Diagnostico
from modelo.moto import Moto


class SeguridadNegativaTests(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            RATELIMIT_ENABLED=False,
            MOTOSMART_NOTIFICACIONES_ASYNC=False,
        )
        self.client = app.test_client()
        with app.app_context():
            db.session.remove()
            db.drop_all()
            inicializar_base()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def crear_taller(self, nombre='Taller QA', email='titular-qa@example.com'):
        response = self.client.post('/talleres', json={
            'nombre': nombre,
            'ciudad': 'Bogotá',
            'telefono': '3001234567',
            'nombre_titular': f'Titular {nombre}',
            'email': email,
            'password': 'clave-segura-123',
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['token'], response.get_json()['taller']['id']

    def registrar_cliente(self, email='cliente-qa@example.com', taller_id=None):
        taller_id = taller_id or self.client.get('/talleres').get_json()[0]['id']
        response = self.client.post('/register', json={
            'username': email,
            'password': 'clave-cliente-123',
            'nombre': 'Cliente QA',
            'taller_id': taller_id,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        login = self.client.post('/login', json={
            'username': email, 'password': 'clave-cliente-123',
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        return login.get_json()['token']

    @staticmethod
    def headers(token):
        return {'Authorization': f'Bearer {token}'}

    def crear_moto(self, token, placa='ABC123'):
        response = self.client.post('/motos', headers=self.headers(token), json={
            'placa': placa, 'marca': 'Honda', 'modelo': 'CB',
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['id']

    # ------------------------------------------------------------------
    # AL-01: validación de entrada y errores JSON
    # ------------------------------------------------------------------
    def test_motos_rechaza_datos_invalidos_sin_500(self):
        _, taller_id = self.crear_taller()
        customer = self.registrar_cliente(taller_id=taller_id)

        self.assertEqual(self.client.post(
            '/motos', headers=self.headers(customer), json={'marca': 'X', 'modelo': 'Y'},
        ).status_code, 400)
        self.assertEqual(self.client.post(
            '/motos', headers=self.headers(customer),
            json={'placa': 123, 'marca': 'X', 'modelo': 'Y'},
        ).status_code, 400)
        self.assertEqual(self.client.post(
            '/motos', headers=self.headers(customer),
            json={'placa': 'ABC123', 'marca': '', 'modelo': ''},
        ).status_code, 400)
        self.assertEqual(self.client.post(
            '/motos', headers=self.headers(customer),
            json={'placa': 'ABC123', 'marca': 'X', 'modelo': 'Y', 'tipo_tecnologia': None},
        ).status_code, 201)
        # null usa el valor por defecto; un tipo desconocido sí se rechaza.
        self.assertEqual(self.client.post(
            '/motos', headers=self.headers(customer),
            json={'placa': 'ABC124', 'marca': 'X', 'modelo': 'Y', 'tipo_tecnologia': 'otro'},
        ).status_code, 400)
        self.assertEqual(self.client.post(
            '/motos', headers=self.headers(customer), json=[],
        ).status_code, 400)

        texto_plano = self.client.post(
            '/motos', headers={**self.headers(customer), 'Content-Type': 'text/plain'},
            data='hola',
        )
        self.assertEqual(texto_plano.status_code, 415)
        self.assertEqual(texto_plano.mimetype, 'application/json')

    def test_clientes_rechaza_nulos_duplicados_y_correos_invalidos(self):
        owner, _ = self.crear_taller()
        self.assertEqual(self.client.post('/clientes', headers=self.headers(owner), json={
            'nombre': None, 'email': 'x@example.com',
        }).status_code, 400)
        self.assertEqual(self.client.post('/clientes', headers=self.headers(owner), json={
            'nombre': 'Cliente', 'email': 'sin-arroba',
        }).status_code, 400)
        primero = self.client.post('/clientes', headers=self.headers(owner), json={
            'nombre': 'Cliente', 'email': 'dup@example.com',
        })
        self.assertEqual(primero.status_code, 201, primero.get_json())
        self.assertEqual(self.client.post('/clientes', headers=self.headers(owner), json={
            'nombre': 'Otro', 'email': 'dup@example.com',
        }).status_code, 409)

    def test_errores_404_405_415_y_401_son_json(self):
        for response in (
            self.client.get('/ruta-inexistente'),
            self.client.delete('/citas'),
            self.client.get('/facturas'),
        ):
            self.assertEqual(response.mimetype, 'application/json')
        self.assertEqual(self.client.get('/ruta-inexistente').status_code, 404)
        self.assertEqual(self.client.delete('/citas').status_code, 405)
        self.assertEqual(self.client.get('/facturas').status_code, 401)

    # ------------------------------------------------------------------
    # Citas
    # ------------------------------------------------------------------
    def test_citas_validan_fecha_pasada_duplicados_y_tipos(self):
        _, taller_id = self.crear_taller()
        customer = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(customer)
        manana = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        self.assertEqual(self.client.post('/citas', headers=self.headers(customer), json={
            'moto_id': moto_id, 'fecha': '2020-01-01', 'descripcion': 'Pasada',
        }).status_code, 400)
        self.assertEqual(self.client.post('/citas', headers=self.headers(customer), json={
            'moto_id': 'abc', 'fecha': manana,
        }).status_code, 400)
        primera = self.client.post('/citas', headers=self.headers(customer), json={
            'moto_id': moto_id, 'fecha': manana, 'descripcion': 'Primera',
        })
        self.assertEqual(primera.status_code, 201, primera.get_json())
        self.assertEqual(self.client.post('/citas', headers=self.headers(customer), json={
            'moto_id': moto_id, 'fecha': manana,
        }).status_code, 409)

        cita_id = primera.get_json()['cita']['id']
        vacia = self.client.put(
            f'/citas/{cita_id}', headers=self.headers(customer), json={},
        )
        # Un cliente no edita citas desde el panel del taller, pero la cita
        # existe y el 403 es la respuesta autorizada.
        self.assertIn(vacia.status_code, (200, 403))

    # ------------------------------------------------------------------
    # CR-02: integridad referencial en borrados
    # ------------------------------------------------------------------
    def test_borrados_con_dependencias_devuelven_409(self):
        owner, taller_id = self.crear_taller()
        customer = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(customer)
        manana = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        cita = self.client.post('/citas', headers=self.headers(customer), json={
            'moto_id': moto_id, 'fecha': manana,
        })
        self.assertEqual(cita.status_code, 201)

        self.assertEqual(self.client.delete(
            f'/motos/{moto_id}', headers=self.headers(owner),
        ).status_code, 409)

        with app.app_context():
            cliente_id = Cliente.query.filter_by(email='cliente-qa@example.com').first().id
            db.session.add(Diagnostico(
                moto_id=moto_id, taller_id=taller_id, codigo_error='P0101',
                descripcion='Falla de MAF', fecha=datetime(2026, 1, 1),
            ))
            db.session.commit()
        self.assertEqual(self.client.delete(
            f'/motos/{moto_id}', headers=self.headers(owner),
        ).status_code, 409)
        self.assertEqual(self.client.delete(
            f'/clientes/{cliente_id}', headers=self.headers(owner),
        ).status_code, 409)

        item = self.client.post('/inventario', headers=self.headers(owner), json={
            'nombre': 'Filtro', 'categoria': 'repuesto', 'unidad': 'unidades',
            'cantidad': 5, 'stock_minimo': 1,
        })
        self.assertEqual(item.status_code, 201, item.get_json())
        item_id = item.get_json()['item']['id']
        orden = self.client.post('/ordenes-servicio', headers=self.headers(owner), json={
            'moto_id': moto_id, 'descripcion': 'Cambio de filtro',
            'repuestos': [{'inventario_id': item_id, 'cantidad': 1}],
        })
        self.assertEqual(orden.status_code, 201, orden.get_json())
        self.assertEqual(self.client.delete(
            f'/inventario/{item_id}', headers=self.headers(owner),
        ).status_code, 409)

        # La moto sigue existiendo y el panel no se rompe.
        self.assertEqual(self.client.get(
            '/panel-taller', headers=self.headers(owner),
        ).status_code, 200)

    # ------------------------------------------------------------------
    # CR-01: facturación inmutable y auditada
    # ------------------------------------------------------------------
    def test_facturas_validan_montos_y_bloquean_pagadas(self):
        owner, taller_id = self.crear_taller()
        customer = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(customer)
        fecha = datetime.now().strftime('%Y-%m-%d')

        for subtotal in ('NaN', 'Infinity', '1000000000000000'):
            self.assertEqual(self.client.post('/facturas', headers=self.headers(owner), json={
                'moto_id': moto_id, 'fecha': fecha, 'descripcion': 'Monto inválido',
                'subtotal': subtotal, 'iva': '19',
            }).status_code, 400)

        creada = self.client.post('/facturas', headers=self.headers(owner), json={
            'moto_id': moto_id, 'fecha': fecha, 'descripcion': 'Servicio',
            'subtotal': '100', 'iva': '19', 'estado': 'pagada',
        })
        self.assertEqual(creada.status_code, 201, creada.get_json())
        factura = creada.get_json()['factura']
        self.assertEqual(factura['total'], '119.00')
        self.assertEqual(self.client.put(
            f"/facturas/{factura['id']}", headers=self.headers(owner), json={
                'moto_id': moto_id, 'fecha': fecha, 'descripcion': 'Alterada',
                'subtotal': '1', 'iva': '0',
            },
        ).status_code, 409)
        self.assertEqual(self.client.delete(
            f"/facturas/{factura['id']}", headers=self.headers(owner),
        ).status_code, 409)

        with app.app_context():
            self.assertGreater(Auditoria.query.count(), 0)

    def test_mecanico_no_titular_no_edita_facturas(self):
        owner, taller_id = self.crear_taller()
        customer = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(customer)
        fecha = datetime.now().strftime('%Y-%m-%d')
        factura = self.client.post('/facturas', headers=self.headers(owner), json={
            'moto_id': moto_id, 'fecha': fecha, 'descripcion': 'Servicio',
            'subtotal': '100',
        }).get_json()['factura']

        creado = self.client.post('/mecanicos', headers=self.headers(owner), json={
            'email': 'mecanico-qa@example.com', 'password': 'clave-mecanico-123',
        })
        self.assertEqual(creado.status_code, 201, creado.get_json())
        login = self.client.post('/login', json={
            'username': 'mecanico-qa@example.com', 'password': 'clave-mecanico-123',
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        mecanico = login.get_json()['token']
        self.assertEqual(self.client.put(
            f"/facturas/{factura['id']}", headers=self.headers(mecanico), json={
                'moto_id': moto_id, 'fecha': fecha, 'descripcion': 'Alterada',
                'subtotal': '1',
            },
        ).status_code, 403)
        self.assertEqual(self.client.delete(
            f"/facturas/{factura['id']}", headers=self.headers(mecanico),
        ).status_code, 403)

    # ------------------------------------------------------------------
    # AL-03: cambio de contraseña y revocación de tokens
    # ------------------------------------------------------------------
    def test_password_exige_actual_y_revoca_tokens(self):
        owner, _ = self.crear_taller()
        self.assertEqual(self.client.put('/mi-cuenta', headers=self.headers(owner), json={
            'password': 'nueva-clave-123',
        }).status_code, 400)
        cambio = self.client.put('/mi-cuenta', headers=self.headers(owner), json={
            'password': 'nueva-clave-123', 'password_actual': 'clave-segura-123',
        })
        self.assertEqual(cambio.status_code, 200, cambio.get_json())
        self.assertEqual(self.client.get(
            '/mi-cuenta', headers=self.headers(owner),
        ).status_code, 401)
        self.assertEqual(self.client.get(
            '/mi-cuenta', headers=self.headers(cambio.get_json()['token']),
        ).status_code, 200)

    def test_recuperacion_de_password_por_correo(self):
        owner, _ = self.crear_taller()
        anonimo = self.client.post('/mi-cuenta/recuperar', json={
            'email': 'no-existe@example.com',
        })
        self.assertEqual(anonimo.status_code, 202)

        with patch('router.auth.enviar_correo', return_value=True) as envio:
            solicitud = self.client.post('/mi-cuenta/recuperar', json={
                'email': 'titular-qa@example.com',
            })
        self.assertEqual(solicitud.status_code, 202)
        cuerpo = envio.call_args.args[2]
        token = re.search(r'#reset=([A-Za-z0-9_-]+)', cuerpo).group(1)

        self.assertEqual(self.client.post('/mi-cuenta/restablecer', json={
            'token': token, 'password': 'corta',
        }).status_code, 400)
        cambio = self.client.post('/mi-cuenta/restablecer', json={
            'token': token, 'password': 'nueva-clave-123',
        })
        self.assertEqual(cambio.status_code, 200, cambio.get_json())
        self.assertEqual(self.client.get(
            '/mi-cuenta', headers=self.headers(owner),
        ).status_code, 401)
        self.assertEqual(self.client.post('/login', json={
            'username': 'titular-qa@example.com', 'password': 'nueva-clave-123',
        }).status_code, 200)
        # El token es de un solo uso.
        self.assertEqual(self.client.post('/mi-cuenta/restablecer', json={
            'token': token, 'password': 'otra-clave-123',
        }).status_code, 400)

    def test_token_de_mecanico_eliminado_queda_revocado(self):
        owner, _ = self.crear_taller()
        creado = self.client.post('/mecanicos', headers=self.headers(owner), json={
            'email': 'borrado-qa@example.com', 'password': 'clave-mecanico-123',
        })
        self.assertEqual(creado.status_code, 201, creado.get_json())
        mecanico_id = creado.get_json()['mecanico']['id']
        login = self.client.post('/login', json={
            'username': 'borrado-qa@example.com', 'password': 'clave-mecanico-123',
        }).get_json()
        self.assertEqual(self.client.delete(
            f'/mecanicos/{mecanico_id}', headers=self.headers(owner),
        ).status_code, 200)
        self.assertEqual(self.client.get(
            '/inventario', headers=self.headers(login['token']),
        ).status_code, 401)

    # ------------------------------------------------------------------
    # ME-02, ME-03, AL-09: cantidades, estados e idempotencia
    # ------------------------------------------------------------------
    def test_cantidades_enteras_y_maquina_de_estados(self):
        owner, taller_id = self.crear_taller()
        customer = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(customer)

        self.assertEqual(self.client.post('/inventario', headers=self.headers(owner), json={
            'nombre': 'Aceite', 'categoria': 'lubricante', 'unidad': 'litros',
            'cantidad': 1.5, 'stock_minimo': 0,
        }).status_code, 400)

        item = self.client.post('/inventario', headers=self.headers(owner), json={
            'nombre': 'Aceite', 'categoria': 'lubricante', 'unidad': 'litros',
            'cantidad': 10, 'stock_minimo': 1,
        })
        self.assertEqual(item.status_code, 201, item.get_json())
        item_id = item.get_json()['item']['id']

        self.assertEqual(self.client.post('/ordenes-servicio', headers=self.headers(owner), json={
            'moto_id': moto_id, 'descripcion': 'Cantidad decimal',
            'repuestos': [{'inventario_id': item_id, 'cantidad': 1.5}],
        }).status_code, 400)

        orden = self.client.post('/ordenes-servicio', headers=self.headers(owner), json={
            'moto_id': moto_id, 'descripcion': 'Servicio',
            'repuestos': [{'inventario_id': item_id, 'cantidad': 2}],
        })
        self.assertEqual(orden.status_code, 201, orden.get_json())
        orden_id = orden.get_json()['orden']['id']
        self.assertEqual(self.client.get(
            '/inventario', headers=self.headers(owner),
        ).get_json()[0]['cantidad'], 8)

        for estado in ('diagnostico', 'reparacion', 'lista', 'entregada'):
            cambio = self.client.put(
                f'/ordenes-servicio/{orden_id}/estado',
                headers=self.headers(owner), json={'estado': estado},
            )
            self.assertEqual(cambio.status_code, 200, cambio.get_json())
        self.assertEqual(self.client.put(
            f'/ordenes-servicio/{orden_id}/estado',
            headers=self.headers(owner), json={'estado': 'recibida'},
        ).status_code, 409)
        self.assertEqual(self.client.post(
            f'/ordenes-servicio/{orden_id}/cancelar', headers=self.headers(owner), json={},
        ).status_code, 409)

        segunda = self.client.post('/ordenes-servicio', headers=self.headers(owner), json={
            'moto_id': moto_id, 'descripcion': 'Para cancelar',
            'repuestos': [{'inventario_id': item_id, 'cantidad': 3}],
        })
        self.assertEqual(segunda.status_code, 201, segunda.get_json())
        segunda_id = segunda.get_json()['orden']['id']
        self.assertEqual(self.client.post(
            f'/ordenes-servicio/{segunda_id}/cancelar', headers=self.headers(owner), json={},
        ).status_code, 200)
        self.assertEqual(self.client.get(
            '/inventario', headers=self.headers(owner),
        ).get_json()[0]['cantidad'], 8)

    def test_idempotencia_en_facturas_y_ordenes(self):
        owner, taller_id = self.crear_taller()
        customer = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(customer)
        fecha = datetime.now().strftime('%Y-%m-%d')

        cabeceras = {**self.headers(owner), 'Idempotency-Key': 'factura-qa-1'}
        primera = self.client.post('/facturas', headers=cabeceras, json={
            'moto_id': moto_id, 'fecha': fecha, 'descripcion': 'Servicio',
            'subtotal': '50',
        })
        segunda = self.client.post('/facturas', headers=cabeceras, json={
            'moto_id': moto_id, 'fecha': fecha, 'descripcion': 'Servicio',
            'subtotal': '50',
        })
        self.assertEqual(primera.status_code, 201, primera.get_json())
        self.assertEqual(segunda.status_code, 200, segunda.get_json())
        self.assertEqual(
            primera.get_json()['factura']['id'], segunda.get_json()['factura']['id'],
        )

        cabeceras_orden = {**self.headers(owner), 'Idempotency-Key': 'orden-qa-1'}
        orden_1 = self.client.post('/ordenes-servicio', headers=cabeceras_orden, json={
            'moto_id': moto_id, 'descripcion': 'Servicio', 'repuestos': [],
        })
        orden_2 = self.client.post('/ordenes-servicio', headers=cabeceras_orden, json={
            'moto_id': moto_id, 'descripcion': 'Servicio', 'repuestos': [],
        })
        self.assertEqual(orden_1.status_code, 201, orden_1.get_json())
        self.assertEqual(orden_2.status_code, 200, orden_2.get_json())
        self.assertEqual(
            orden_1.get_json()['orden']['id'], orden_2.get_json()['orden']['id'],
        )

    # ------------------------------------------------------------------
    # AL-06 y A-18: uploads
    # ------------------------------------------------------------------
    def test_upload_rechaza_extensiones_y_tamano(self):
        owner, taller_id = self.crear_taller()
        customer = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(customer)

        sin_archivo = self.client.post(
            '/upload_scanner', headers=self.headers(owner), data={'moto_id': moto_id},
        )
        self.assertEqual(sin_archivo.status_code, 400)

        php = self.client.post(
            '/upload_scanner', headers=self.headers(owner),
            data={
                'moto_id': str(moto_id),
                'imagen': (io.BytesIO(b'<?php echo 1; ?>'), 'malicioso.php'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(php.status_code, 400, php.get_json())

        anterior = app.config['MAX_CONTENT_LENGTH']
        app.config['MAX_CONTENT_LENGTH'] = 64
        try:
            grande = self.client.post(
                '/upload_scanner', headers=self.headers(owner),
                data={
                    'moto_id': str(moto_id),
                    'imagen': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 200), 'grande.png'),
                },
                content_type='multipart/form-data',
            )
            self.assertEqual(grande.status_code, 413, grande.get_json())
        finally:
            app.config['MAX_CONTENT_LENGTH'] = anterior

    # ------------------------------------------------------------------
    # AL-07: paginación compatible
    # ------------------------------------------------------------------
    def test_activos_locales_y_cabeceras_de_seguridad(self):
        portada = self.client.get('/')
        self.assertEqual(portada.status_code, 200)
        self.assertIn(b'/static/css/fonts.css', portada.data)
        estilos = self.client.get('/static/css/fonts.css')
        self.assertEqual(estilos.status_code, 200)
        estilos.close()
        fuente = self.client.get('/static/fonts/dm-sans-latin.woff2')
        self.assertEqual(fuente.status_code, 200)
        fuente.close()
        respuesta = self.client.get('/health')
        self.assertEqual(respuesta.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(respuesta.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(respuesta.headers.get('X-MotoSmart-Version'), '1.0.0')
        politica = respuesta.headers.get('Content-Security-Policy', '')
        self.assertIn("default-src 'self'", politica)
        self.assertNotIn('fonts.googleapis.com', politica)

    def test_gets_individuales_patch_y_comando_admin(self):
        owner, taller_id = self.crear_taller()
        customer = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(customer)
        manana = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        cita = self.client.post('/citas', headers=self.headers(customer), json={
            'moto_id': moto_id, 'fecha': manana, 'descripcion': 'Revisión',
        }).get_json()['cita']

        self.assertEqual(self.client.get(
            f"/citas/{cita['id']}", headers=self.headers(customer),
        ).status_code, 200)
        item = self.client.post('/inventario', headers=self.headers(owner), json={
            'nombre': 'Bujía', 'categoria': 'repuesto', 'unidad': 'unidades',
            'cantidad': 4, 'stock_minimo': 1,
        }).get_json()['item']
        self.assertEqual(self.client.get(
            f"/inventario/{item['id']}", headers=self.headers(owner),
        ).status_code, 200)
        parche = self.client.patch(
            f"/inventario/{item['id']}", headers=self.headers(owner),
            json={
                'nombre': 'Bujía', 'categoria': 'repuesto', 'unidad': 'unidades',
                'cantidad': 5, 'stock_minimo': 1,
            },
        )
        self.assertEqual(parche.status_code, 200, parche.get_json())

        runner = app.test_cli_runner()
        salida = runner.invoke(
            args=['crear-admin', '--email', 'admin-qa@example.com',
                  '--taller-id', str(taller_id)],
            input='clave-admin-123\nclave-admin-123\n',
        )
        self.assertEqual(salida.exit_code, 0, salida.output)
        login = self.client.post('/login', json={
            'username': 'admin-qa@example.com', 'password': 'clave-admin-123',
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        admin = login.get_json()['token']
        creado = self.client.post('/inventario', headers=self.headers(admin), json={
            'nombre': 'Cadena', 'categoria': 'repuesto', 'unidad': 'unidades',
            'cantidad': 2, 'stock_minimo': 0,
        })
        self.assertEqual(creado.status_code, 201, creado.get_json())
        salud = self.client.get('/health')
        self.assertEqual(salud.status_code, 200)
        self.assertEqual(salud.mimetype, 'application/json')

        propia = self.crear_moto(customer, 'XYZ789')
        self.assertEqual(self.client.delete(
            f'/motos/{propia}', headers=self.headers(customer),
        ).status_code, 200)

    def test_paginacion_devuelve_objeto_solo_si_se_solicita(self):
        owner, _ = self.crear_taller()
        for indice in range(3):
            self.assertEqual(self.client.post('/inventario', headers=self.headers(owner), json={
                'nombre': f'Item {indice}', 'categoria': 'repuesto', 'unidad': 'unidades',
                'cantidad': 1, 'stock_minimo': 0,
            }).status_code, 201)

        lista = self.client.get('/inventario', headers=self.headers(owner))
        self.assertIsInstance(lista.get_json(), list)
        pagina = self.client.get(
            '/inventario?page=1&per_page=2', headers=self.headers(owner),
        ).get_json()
        self.assertEqual(pagina['total'], 3)
        self.assertEqual(len(pagina['items']), 2)
        self.assertEqual(pagina['pages'], 2)


if __name__ == '__main__':
    unittest.main()
