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
os.environ['MOTOSMART_DATABASE_URL'] = 'sqlite://'
os.environ['MOTOSMART_JWT_SECRET_KEY'] = 'test-only-key-with-at-least-32-characters'
sys.modules.setdefault(
    'easyocr',
    SimpleNamespace(Reader=lambda languages: SimpleNamespace(readtext=lambda path: [])),
)

from app import app, inicializar_base
from db import db
from modelo.diagnostico import Diagnostico
from modelo.clientes import Cliente
from modelo.moto import Moto


class MultiTenantTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
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

    def test_public_landing_and_registration_template_render(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Quiénes somos'.encode(), response.data)
        self.assertIn('register-workshop'.encode(), response.data)
        self.assertIn('Registrar mi taller'.encode(), response.data)
        self.assertNotIn(b'aria-label="Navegaci\xc3\xb3n principal"', response.data)
        self.assertIn(b'<symbol id="icon-home"', response.data)
        self.assertIn(b'<use href="#icon-home">', response.data)
        self.assertEqual(response.data.count(b'class="desktop-app"'), 15)
        self.assertIn(b'data-app-roles="mecanico admin titular"', response.data)
        self.assertIn(b'data-app-roles="titular"', response.data)
        self.assertIn(b'id="view-escritorio"', response.data)
        self.assertIn(b'class="desktop-apps"', response.data)
        self.assertIn(b'data-go="inventario"', response.data)
        self.assertIn(b'id="back-to-desktop"', response.data)
        self.assertIn(b'data-app-roles="mecanico titular" data-go="scanner"', response.data)
        self.assertIn(b'id="account-menu-shell" class="account-menu hidden"', response.data)
        self.assertIn(b'<span>Confirmar contrase\xc3\xb1a</span>', response.data)
        self.assertIn(b'name="password_confirm"', response.data)

    def test_database_reset_command_requires_explicit_confirmation(self):
        self.crear_taller('Taller antes del reinicio', 'reinicio@example.com')
        runner = app.test_cli_runner()
        rejected = runner.invoke(args=['reiniciar-base-talleres'])
        self.assertNotEqual(rejected.exit_code, 0)
        self.assertEqual(len(self.client.get('/talleres').get_json()), 1)

        confirmed = runner.invoke(args=['reiniciar-base-talleres', '--confirmar'])
        self.assertEqual(confirmed.exit_code, 0, confirmed.output)
        self.assertEqual(self.client.get('/talleres').get_json(), [])

    def crear_taller(self, nombre, email):
        response = self.client.post('/talleres', json={
            'nombre': nombre,
            'ciudad': 'Bogotá',
            'telefono': '3001234567',
            'nombre_titular': f'Titular {nombre}',
            'email': email,
            'password': 'clave-segura-123',
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['token']

    def registrar_cliente(self, email, taller_id):
        response = self.client.post('/register', json={
            'username': email,
            'password': 'clave-cliente-123',
            'nombre': 'Cliente de prueba',
            'taller_id': taller_id,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        response = self.client.post('/login', json={
            'username': email,
            'password': 'clave-cliente-123',
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['token']

    @staticmethod
    def headers(token):
        return {'Authorization': f'Bearer {token}'}

    def test_registration_and_inventory_are_scoped_to_selected_workshop(self):
        owner_a = self.crear_taller('Taller A', 'titular-a@example.com')
        owner_b = self.crear_taller('Taller B', 'titular-b@example.com')
        talleres = self.client.get('/talleres').get_json()
        taller_a = next(taller for taller in talleres if taller['nombre'] == 'Taller A')
        taller_b = next(taller for taller in talleres if taller['nombre'] == 'Taller B')
        account = self.client.get('/mi-cuenta', headers=self.headers(owner_a))
        self.assertEqual(account.status_code, 200, account.get_json())
        self.assertEqual(account.get_json()['taller_nombre'], 'Taller A')
        self.assertEqual(account.get_json()['nombre'], 'Titular Taller A')

        missing_workshop = self.client.post('/register', json={
            'username': 'cliente@example.com',
            'password': 'clave-cliente-123',
            'nombre': 'Cliente',
        })
        self.assertEqual(missing_workshop.status_code, 400)
        customer_a = self.registrar_cliente('cliente-a@example.com', taller_a['id'])
        customer_b = self.registrar_cliente('cliente-b@example.com', taller_b['id'])

        moto = self.client.post('/motos', headers=self.headers(customer_a), json={
            'placa': 'ABC123',
            'marca': 'Honda',
            'modelo': 'CB',
        })
        self.assertEqual(moto.status_code, 201, moto.get_json())
        self.assertEqual(self.client.get('/motos', headers=self.headers(customer_b)).get_json(), [])
        foreign_appointment = self.client.post(
            '/citas',
            headers=self.headers(customer_b),
            json={
                'moto_id': moto.get_json()['id'],
                'fecha': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
                'descripcion': 'No debe asignarse a otro taller',
            },
        )
        self.assertEqual(foreign_appointment.status_code, 404)

        item_a = self.client.post('/inventario', headers=self.headers(owner_a), json={
            'nombre': 'Aceite',
            'categoria': 'lubricante',
            'unidad': 'litros',
            'cantidad': 4,
            'stock_minimo': 1,
        })
        self.assertEqual(item_a.status_code, 201, item_a.get_json())
        self.assertEqual(
            self.client.get('/inventario', headers=self.headers(owner_b)).get_json(),
            [],
        )
        other_workshop_item = self.client.put(
            f"/inventario/{item_a.get_json()['item']['id']}",
            headers=self.headers(owner_b),
            json={
                'nombre': 'Aceite alterado',
                'categoria': 'lubricante',
                'unidad': 'litros',
                'cantidad': 4,
                'stock_minimo': 1,
            },
        )
        self.assertEqual(other_workshop_item.status_code, 404)

    def test_historical_client_must_verify_email_before_claiming_data(self):
        self.crear_taller('Taller histórico', 'titular-historico@example.com')
        taller = self.client.get('/talleres').get_json()[0]
        with app.app_context():
            cliente = Cliente(
                nombre='Cliente histórico',
                email='historico@example.com',
                taller_id=taller['id'],
            )
            db.session.add(cliente)
            db.session.flush()
            moto = Moto(
                placa='HIS123',
                marca='Suzuki',
                modelo='GN',
                cliente_id=cliente.id,
                taller_id=taller['id'],
            )
            db.session.add(moto)
            db.session.commit()
            moto_id = moto.id

        with patch('router.auth.enviar_correo', return_value=True) as send_email:
            registration = self.client.post('/register', json={
                'username': 'historico@example.com',
                'password': 'clave-historial-123',
                'nombre': 'Cliente verificado',
                'taller_id': taller['id'],
            })
        self.assertEqual(registration.status_code, 202, registration.get_json())
        self.assertIsNone(self.client.post('/login', json={
            'username': 'historico@example.com',
            'password': 'clave-historial-123',
        }).get_json().get('token'))
        email_body = send_email.call_args.args[2]
        token = re.search(r'#claim=([A-Za-z0-9_-]+)', email_body).group(1)
        verification = self.client.post('/register/verify', json={'token': token})
        self.assertEqual(verification.status_code, 201, verification.get_json())

        login = self.client.post('/login', json={
            'username': 'historico@example.com',
            'password': 'clave-historial-123',
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        motos = self.client.get(
            '/motos', headers=self.headers(login.get_json()['token'])
        ).get_json()
        self.assertEqual([item['id'] for item in motos], [moto_id])

    def test_transfer_moves_bikes_and_three_diagnostics_but_not_service_records(self):
        owner_a = self.crear_taller('Origen', 'titular-origen@example.com')
        owner_b = self.crear_taller('Destino', 'titular-destino@example.com')
        talleres = self.client.get('/talleres').get_json()
        taller_a = next(taller for taller in talleres if taller['nombre'] == 'Origen')
        taller_b = next(taller for taller in talleres if taller['nombre'] == 'Destino')
        customer = self.registrar_cliente('mudanza@example.com', taller_a['id'])

        motorcycle = self.client.post('/motos', headers=self.headers(customer), json={
            'placa': 'XYZ789',
            'marca': 'Yamaha',
            'modelo': 'FZ',
        })
        self.assertEqual(motorcycle.status_code, 201, motorcycle.get_json())
        moto_id = motorcycle.get_json()['id']

        appointment = self.client.post('/citas', headers=self.headers(customer), json={
            'moto_id': moto_id,
            'fecha': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
            'descripcion': 'Servicio pendiente',
        })
        self.assertEqual(appointment.status_code, 201, appointment.get_json())

        invoice = self.client.post('/facturas', headers=self.headers(owner_a), json={
            'moto_id': moto_id,
            'fecha': datetime.now().strftime('%Y-%m-%d'),
            'descripcion': 'Servicio anterior',
            'subtotal': '10000',
            'iva': '19',
        })
        self.assertEqual(invoice.status_code, 201, invoice.get_json())
        cross_shop_invoice = self.client.post('/facturas', headers=self.headers(owner_b), json={
            'moto_id': moto_id,
            'fecha': datetime.now().strftime('%Y-%m-%d'),
            'descripcion': 'Intento de acceso cruzado',
            'subtotal': '10000',
        })
        self.assertEqual(cross_shop_invoice.status_code, 400)

        order = self.client.post('/ordenes-servicio', headers=self.headers(owner_a), json={
            'moto_id': moto_id,
            'descripcion': 'Orden del taller de origen',
            'repuestos': [],
        })
        self.assertEqual(order.status_code, 201, order.get_json())

        cross_shop_order = self.client.post('/ordenes-servicio', headers=self.headers(owner_b), json={
            'moto_id': moto_id,
            'descripcion': 'Intento de acceso cruzado',
            'repuestos': [],
        })
        self.assertEqual(cross_shop_order.status_code, 404)

        with app.app_context():
            db.session.add_all([
                Diagnostico(
                    moto_id=moto_id,
                    taller_id=taller_a['id'],
                    codigo_error=f'P{i:03}',
                    descripcion=f'Diagnóstico {i}',
                    fecha=datetime(2025, 1, i),
                )
                for i in range(1, 5)
            ])
            db.session.commit()

        with patch('router.auth.enviar_correo', return_value=True) as send_email:
            transfer = self.client.post(
                '/mi-cuenta/cambiar-taller',
                headers=self.headers(customer),
                json={'taller_id': taller_b['id']},
            )
        self.assertEqual(transfer.status_code, 202, transfer.get_json())
        email_body = send_email.call_args.args[2]
        token = re.search(r'#transfer=([A-Za-z0-9_-]+)', email_body).group(1)
        verified = self.client.post('/register/verify', json={'token': token})
        self.assertEqual(verified.status_code, 200, verified.get_json())

        moved_motos = self.client.get('/motos', headers=self.headers(customer)).get_json()
        self.assertEqual(len(moved_motos), 1)
        self.assertEqual(moved_motos[0]['placa'], 'XYZ789')
        self.assertNotEqual(moved_motos[0]['id'], moto_id)
        moved_moto_id = moved_motos[0]['id']
        moved_diagnostics = self.client.get(
            '/mis_diagnosticos', headers=self.headers(customer)
        ).get_json()
        self.assertEqual(len(moved_diagnostics), 3)
        self.assertEqual(
            {item['codigo_error'] for item in moved_diagnostics},
            {'P002', 'P003', 'P004'},
        )
        self.assertTrue(all(item['moto_id'] == moved_moto_id for item in moved_diagnostics))
        self.assertEqual(
            self.client.get('/mis_citas', headers=self.headers(customer)).get_json(),
            [],
        )
        self.assertEqual(
            self.client.get('/mis_facturas', headers=self.headers(customer)).get_json(),
            [],
        )

        self.assertEqual(
            self.client.get('/motos', headers=self.headers(owner_a)).get_json(),
            [],
        )
        self.assertEqual(
            len(self.client.get('/diagnosticos', headers=self.headers(owner_a)).get_json()),
            4,
        )
        self.assertEqual(
            len(self.client.get('/facturas', headers=self.headers(owner_a)).get_json()),
            1,
        )
        self.assertEqual(
            len(self.client.get('/ordenes-servicio', headers=self.headers(owner_a)).get_json()),
            1,
        )
        self.assertEqual(
            self.client.get('/facturas', headers=self.headers(owner_b)).get_json(),
            [],
        )
        self.assertEqual(
            self.client.get('/ordenes-servicio', headers=self.headers(owner_b)).get_json(),
            [],
        )
        self.assertEqual(
            len(self.client.get('/citas/detalle', headers=self.headers(owner_a)).get_json()),
            1,
        )
        self.assertEqual(
            self.client.get('/citas/detalle', headers=self.headers(owner_b)).get_json(),
            [],
        )

        with patch('router.auth.enviar_correo', return_value=True) as send_email:
            return_request = self.client.post(
                '/mi-cuenta/cambiar-taller',
                headers=self.headers(customer),
                json={'taller_id': taller_a['id']},
            )
        self.assertEqual(return_request.status_code, 202, return_request.get_json())
        return_email = send_email.call_args.args[2]
        return_token = re.search(r'#transfer=([A-Za-z0-9_-]+)', return_email).group(1)
        returned = self.client.post('/register/verify', json={'token': return_token})
        self.assertEqual(returned.status_code, 200, returned.get_json())
        returned_motos = self.client.get(
            '/motos', headers=self.headers(customer)
        ).get_json()
        self.assertEqual(len(returned_motos), 1)
        self.assertEqual(returned_motos[0]['id'], moto_id)
        returned_diagnostics = self.client.get(
            '/mis_diagnosticos', headers=self.headers(customer)
        ).get_json()
        self.assertEqual(len(returned_diagnostics), 4)


if __name__ == '__main__':
    unittest.main()
