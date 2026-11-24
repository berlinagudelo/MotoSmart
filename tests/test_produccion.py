"""Pruebas de los controles añadidos para un despliegue de producción robusto.

Cubren sesión en cookie HttpOnly + CSRF, rate limiting, cola persistente de OCR,
exportación/anonimización de datos y migraciones Alembic.
"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
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
from modelo.citas import Cita
from modelo.clientes import Cliente
from modelo.diagnostico import Diagnostico
from modelo.moto import Moto
from modelo.orden_servicio import OrdenServicio
from modelo.registro_pendiente import RegistroPendiente
from modelo.taller import Taller
from modelo.trabajo_ocr import TrabajoOCR
from modelo.usuario import Usuario
from services import seguridad
from services.ocr_queue import procesar_trabajo, reclamar_trabajo
from services.privacidad import anonimizar_usuario, aplicar_retencion


class BaseProduccionTests(unittest.TestCase):
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
        seguridad._registros.clear()

    def crear_taller(self, email='titular-prod@example.com'):
        response = self.client.post('/talleres', json={
            'nombre': 'Taller Producción',
            'ciudad': 'Bogotá',
            'telefono': '3001234567',
            'nombre_titular': 'Titular Producción',
            'email': email,
            'password': 'clave-segura-123',
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['token'], response.get_json()['taller']['id']

    def registrar_cliente(self, email='cliente-prod@example.com', taller_id=None):
        taller_id = taller_id or self.client.get('/talleres').get_json()[0]['id']
        response = self.client.post('/register', json={
            'username': email,
            'password': 'clave-cliente-123',
            'nombre': 'Cliente Producción',
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

    def crear_moto(self, token, placa='PRO123', electronica=True):
        response = self.client.post('/motos', headers=self.headers(token), json={
            'placa': placa,
            'marca': 'Honda',
            'modelo': 'CB',
            'tipo_tecnologia': 'electronica' if electronica else 'no_electronica',
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['id']


class SesionCookieTests(BaseProduccionTests):
    def test_login_usa_cookie_httponly_y_csrf(self):
        token, _ = self.crear_taller()
        self.assertTrue(token)
        anterior = app.config['MOTOSMART_RETURN_TOKEN_IN_BODY']
        app.config['MOTOSMART_RETURN_TOKEN_IN_BODY'] = False
        try:
            response = self.client.post('/login', json={
                'username': 'titular-prod@example.com',
                'password': 'clave-segura-123',
            })
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertNotIn('token', response.get_json())
            cookies = response.headers.getlist('Set-Cookie')
            acceso = next(item for item in cookies if item.startswith('access_token_cookie='))
            self.assertIn('HttpOnly', acceso)
            self.assertIn('SameSite=Strict', acceso)

            sesion = self.client.get('/sesion')
            self.assertEqual(sesion.status_code, 200, sesion.get_json())
            self.assertEqual(sesion.get_json()['usuario']['rol'], 'mecanico')

            sin_csrf = self.client.put('/mi-cuenta', json={})
            self.assertEqual(sin_csrf.status_code, 401, sin_csrf.get_json())

            csrf = self.client.get_cookie('csrf_access_token')
            self.assertIsNotNone(csrf)
            con_csrf = self.client.put(
                '/mi-cuenta', json={}, headers={'X-CSRF-TOKEN': csrf.value},
            )
            self.assertEqual(con_csrf.status_code, 200, con_csrf.get_json())
        finally:
            app.config['MOTOSMART_RETURN_TOKEN_IN_BODY'] = anterior


class RateLimitTests(BaseProduccionTests):
    def test_ventana_en_memoria_limita_y_reintenta(self):
        clave = 'prueba-rate-limit'
        self.assertEqual(seguridad.permitir_peticion(clave, 2, 60), (True, 0))
        self.assertEqual(seguridad.permitir_peticion(clave, 2, 60), (True, 0))
        permitido, reintentar = seguridad.permitir_peticion(clave, 2, 60)
        self.assertFalse(permitido)
        self.assertGreaterEqual(reintentar, 1)

    def test_backend_redis_se_usa_si_esta_disponible(self):
        class RedisFalso:
            def eval(self, *args):
                return [1, 0]

        with patch.object(seguridad, 'cliente_redis', return_value=RedisFalso()):
            self.assertEqual(seguridad.permitir_peticion('redis-clave', 5, 60), (True, 0))


class ColaOCRTests(BaseProduccionTests):
    def setUp(self):
        super().setUp()
        self.directorio = tempfile.mkdtemp(prefix='motorsmart-ocr-')
        self.anterior = app.config.get('MOTOSMART_OCR_DIR')
        app.config['MOTOSMART_OCR_DIR'] = self.directorio

    def tearDown(self):
        app.config['MOTOSMART_OCR_DIR'] = self.anterior
        super().tearDown()

    def test_upload_encola_y_worker_crea_diagnostico(self):
        owner, taller_id = self.crear_taller()
        cliente = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(cliente)

        response = self.client.post(
            '/upload_scanner',
            headers=self.headers(owner),
            data={
                'moto_id': str(moto_id),
                'imagen': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 80), 'scan.png'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 202, response.get_json())
        trabajo_id = response.get_json()['trabajo']['id']

        with app.app_context(), patch(
            'services.ocr_queue.procesar_imagen',
            return_value=(
                'P0300',
                'P0300 - Fallo de encendido',
                [{'codigo': 'P0300', 'descripcion': 'Fallo de encendido'}],
            ),
        ):
            reclamado = reclamar_trabajo()
            self.assertEqual(reclamado, trabajo_id)
            _, estado, error = procesar_trabajo(trabajo_id)
            self.assertEqual(estado, 'completado', error)
            self.assertEqual(Diagnostico.query.count(), 1)
            trabajo = db.session.get(TrabajoOCR, trabajo_id)
            self.assertEqual(trabajo.diagnostico_id, Diagnostico.query.first().id)

        estado = self.client.get(
            f'/scanner/trabajos/{trabajo_id}', headers=self.headers(owner),
        )
        self.assertEqual(estado.status_code, 200, estado.get_json())
        self.assertEqual(estado.get_json()['trabajo']['estado'], 'completado')
        self.assertEqual(
            estado.get_json()['trabajo']['resultado']['codigo_error'], 'P0300',
        )

    def test_imagen_ilegible_marca_error_sin_reintentar(self):
        owner, taller_id = self.crear_taller()
        cliente = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(cliente)
        response = self.client.post(
            '/upload_scanner',
            headers=self.headers(owner),
            data={
                'moto_id': str(moto_id),
                'imagen': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 80), 'scan.png'),
            },
            content_type='multipart/form-data',
        )
        trabajo_id = response.get_json()['trabajo']['id']
        from services.ocr_procesamiento import ErrorOCRNoLegible

        with app.app_context(), patch(
            'services.ocr_queue.procesar_imagen',
            side_effect=ErrorOCRNoLegible('No se detectó ningún código.'),
        ):
            reclamar_trabajo()
            _, estado, _ = procesar_trabajo(trabajo_id)
            self.assertEqual(estado, 'error')
            self.assertEqual(Diagnostico.query.count(), 0)


class PrivacidadTests(BaseProduccionTests):
    def test_exportar_y_anonimizar_cuenta(self):
        _, taller_id = self.crear_taller()
        cliente = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(cliente)

        exportado = self.client.get('/mi-cuenta/exportar', headers=self.headers(cliente))
        self.assertEqual(exportado.status_code, 200, exportado.get_json())
        datos = exportado.get_json()
        self.assertEqual(datos['cuenta']['email'], 'cliente-prod@example.com')
        self.assertEqual(len(datos['motos']), 1)
        self.assertEqual(datos['motos'][0]['id'], moto_id)
        self.assertIn('attachment', exportado.headers['Content-Disposition'])

        mal = self.client.delete('/mi-cuenta', headers=self.headers(cliente), json={
            'password': 'clave-cliente-123', 'confirmar': 'NO',
        })
        self.assertEqual(mal.status_code, 400)
        incorrecta = self.client.delete('/mi-cuenta', headers=self.headers(cliente), json={
            'password': 'incorrecta-123', 'confirmar': 'ELIMINAR',
        })
        self.assertEqual(incorrecta.status_code, 401)

        borrada = self.client.delete('/mi-cuenta', headers=self.headers(cliente), json={
            'password': 'clave-cliente-123', 'confirmar': 'ELIMINAR',
        })
        self.assertEqual(borrada.status_code, 200, borrada.get_json())
        cookies = borrada.headers.getlist('Set-Cookie')
        self.assertTrue(any(
            item.startswith('access_token_cookie=;') for item in cookies
        ), cookies)

        relogin = self.client.post('/login', json={
            'username': 'cliente-prod@example.com', 'password': 'clave-cliente-123',
        })
        self.assertEqual(relogin.status_code, 401)

        with app.app_context():
            from modelo.moto import Moto
            from modelo.usuario import Usuario
            usuario = Usuario.query.filter_by(rol='cliente').one()
            self.assertFalse(usuario.activo)
            self.assertTrue(usuario.username.startswith('eliminado-'))
            perfil = Cliente.query.one()
            self.assertTrue(perfil.email.startswith('anon-'))
            self.assertIsNone(perfil.telefono)
            moto = db.session.get(Moto, moto_id)
            self.assertTrue(moto.placa.startswith('ANON-'))
            self.assertTrue(moto.transferida)


class RetencionTests(BaseProduccionTests):
    def test_retencion_elimina_tokens_ocr_y_auditoria_antigua(self):
        _, taller_id = self.crear_taller()
        cliente = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(cliente)
        with app.app_context():
            ahora = datetime.now(timezone.utc)
            db.session.add(RegistroPendiente(
                email='viejo@example.com',
                token_hash='a' * 64,
                expires_at=int((ahora - timedelta(days=5)).timestamp()),
                tipo='registro',
            ))
            db.session.add(Auditoria(
                entidad='usuario', entidad_id=1, accion='prueba',
                taller_id=taller_id, creada_en=ahora - timedelta(days=900),
            ))
            db.session.add(TrabajoOCR(
                taller_id=taller_id, moto_id=moto_id, estado='completado',
                ruta_archivo='/tmp/inexistente.png', tamano=10,
                creado_en=ahora - timedelta(days=200),
            ))
            db.session.commit()

            simulado = aplicar_retencion(
                dias_auditoria=30, dias_ocr=30, dry_run=True,
            )
            self.assertEqual(simulado['registros_pendientes'], 1)
            self.assertEqual(simulado['trabajos_ocr'], 1)
            self.assertEqual(simulado['auditoria'], 1)

            aplicado = aplicar_retencion(dias_auditoria=30, dias_ocr=30)
            self.assertEqual(aplicado['registros_pendientes'], 1)
            self.assertEqual(RegistroPendiente.query.count(), 0)
            self.assertEqual(TrabajoOCR.query.count(), 0)
            self.assertEqual(Auditoria.query.filter_by(accion='prueba').count(), 0)


class ArchivosOCRTests(BaseProduccionTests):
    def test_retencion_elimina_la_imagen_del_trabajo_ocr(self):
        _, taller_id = self.crear_taller()
        cliente = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(cliente)
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / 'scan.png'
            ruta.write_bytes(b'\x89PNG\r\n\x1a\n')
            with app.app_context():
                ahora = datetime.now(timezone.utc)
                db.session.add(TrabajoOCR(
                    taller_id=taller_id, moto_id=moto_id, estado='completado',
                    ruta_archivo=str(ruta), tamano=8,
                    creado_en=ahora - timedelta(days=120),
                ))
                db.session.commit()
                resumen = aplicar_retencion(dias_auditoria=30, dias_ocr=30)
                self.assertEqual(resumen['trabajos_ocr'], 1)
                self.assertEqual(TrabajoOCR.query.count(), 0)
            self.assertFalse(ruta.exists())

    def test_anonimizar_cliente_elimina_sus_imagenes_ocr(self):
        _, taller_id = self.crear_taller()
        cliente = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(cliente)
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / 'scan.png'
            ruta.write_bytes(b'\x89PNG\r\n\x1a\n')
            with app.app_context():
                db.session.add(TrabajoOCR(
                    taller_id=taller_id, moto_id=moto_id, estado='completado',
                    ruta_archivo=str(ruta), tamano=8,
                ))
                db.session.commit()
                usuario = Usuario.query.filter_by(
                    username='cliente-prod@example.com',
                ).one()
                resumen = anonimizar_usuario(usuario, motivo='prueba')
                db.session.commit()
                self.assertEqual(resumen['trabajos_ocr_eliminados'], 1)
                self.assertEqual(TrabajoOCR.query.count(), 0)
            self.assertFalse(ruta.exists())


class AnonimizacionAlcanceTests(BaseProduccionTests):
    def test_anonimizar_personal_no_altera_clientes_de_otro_taller(self):
        _, taller_a = self.crear_taller()
        with app.app_context():
            titular = Usuario.query.filter_by(
                username='titular-prod@example.com',
            ).one()
            otro = Taller(nombre='Taller Ajeno', ciudad='Cali', telefono='3000000000')
            db.session.add(otro)
            db.session.flush()
            db.session.add(Cliente(
                nombre='Cliente Ajeno', email='empleado@example.com',
                telefono='3111111111', taller_id=otro.id,
            ))
            mecanico = Usuario(
                username='empleado@example.com', rol='mecanico',
                nombre='Empleado', taller_id=taller_a, creado_por_id=titular.id,
            )
            mecanico.set_password('clave-empleado-123')
            db.session.add(mecanico)
            db.session.commit()

            resumen = anonimizar_usuario(mecanico, motivo='prueba')
            db.session.commit()
            self.assertEqual(resumen['clientes_anonimizados'], 0)
            ajeno = Cliente.query.filter_by(taller_id=otro.id).one()
            self.assertEqual(ajeno.email, 'empleado@example.com')
            self.assertEqual(ajeno.nombre, 'Cliente Ajeno')
            self.assertEqual(ajeno.telefono, '3111111111')

    def test_anonimizar_cliente_cubre_todos_sus_talleres(self):
        _, taller_a = self.crear_taller()
        self.registrar_cliente(taller_id=taller_a)
        with app.app_context():
            otro = Taller(nombre='Taller Ajeno', ciudad='Cali', telefono='3000000000')
            db.session.add(otro)
            db.session.flush()
            db.session.add(Cliente(
                nombre='Cliente Producción', email='cliente-prod@example.com',
                telefono='3222222222', taller_id=otro.id,
            ))
            db.session.commit()

            usuario = Usuario.query.filter_by(
                username='cliente-prod@example.com',
            ).one()
            resumen = anonimizar_usuario(usuario, motivo='prueba')
            db.session.commit()
            self.assertEqual(resumen['clientes_anonimizados'], 2)
            self.assertEqual(
                Cliente.query.filter(Cliente.email.like('anon-%')).count(), 2,
            )


class VerificacionTallerTests(BaseProduccionTests):
    def test_crear_taller_en_produccion_exige_verificar_correo(self):
        anterior = app.config['MOTOSMART_REQUIRE_EMAIL_VERIFICATION']
        app.config['MOTOSMART_REQUIRE_EMAIL_VERIFICATION'] = True
        try:
            with patch('router.auth.enviar_correo', return_value=True), patch(
                'router.auth.secrets.token_urlsafe',
                return_value='token-taller-fijo',
            ):
                respuesta = self.client.post('/talleres', json={
                    'nombre': 'Taller Verificado',
                    'ciudad': 'Bogotá',
                    'telefono': '3001234567',
                    'nombre_titular': 'Titular Verificado',
                    'email': 'titular-verificado@example.com',
                    'password': 'clave-segura-123',
                })
            self.assertEqual(respuesta.status_code, 202, respuesta.get_json())
            with app.app_context():
                self.assertEqual(Taller.query.count(), 0)
                self.assertEqual(Usuario.query.count(), 0)
                registro = RegistroPendiente.query.filter_by(tipo='taller').one()
                self.assertIsNone(registro.taller_id)
                self.assertEqual(
                    json.loads(registro.datos)['ciudad'], 'Bogotá',
                )

            verificado = self.client.post(
                '/register/verify', json={'token': 'token-taller-fijo'},
            )
            self.assertEqual(verificado.status_code, 201, verificado.get_json())
            with app.app_context():
                taller = Taller.query.one()
                titular = Usuario.query.filter_by(
                    username='titular-verificado@example.com',
                ).one()
                self.assertEqual(titular.taller_id, taller.id)
                self.assertEqual(titular.rol, 'mecanico')
                self.assertTrue(titular.email_verificado)
                self.assertTrue(titular.check_password('clave-segura-123'))
                self.assertEqual(RegistroPendiente.query.count(), 0)

            login = self.client.post('/login', json={
                'username': 'titular-verificado@example.com',
                'password': 'clave-segura-123',
            })
            self.assertEqual(login.status_code, 200, login.get_json())
        finally:
            app.config['MOTOSMART_REQUIRE_EMAIL_VERIFICATION'] = anterior


class RendimientoConsultasTests(BaseProduccionTests):
    def test_prioridades_devuelve_solo_el_ultimo_diagnostico_por_moto(self):
        owner, taller_id = self.crear_taller()
        cliente = self.registrar_cliente(taller_id=taller_id)
        moto_uno = self.crear_moto(cliente, placa='PRI001')
        moto_dos = self.crear_moto(cliente, placa='PRI002')
        moto_tres = self.crear_moto(cliente, placa='PRI003')
        with app.app_context():
            ahora = datetime.now(timezone.utc)
            db.session.add_all([
                Diagnostico(
                    moto_id=moto_uno, taller_id=taller_id, codigo_error='P0300',
                    descripcion='Diagnóstico antiguo', fecha=ahora - timedelta(days=2),
                ),
                Diagnostico(
                    moto_id=moto_uno, taller_id=taller_id, codigo_error='P0171',
                    descripcion='Diagnóstico reciente', fecha=ahora - timedelta(days=1),
                ),
                Diagnostico(
                    moto_id=moto_dos, taller_id=taller_id, codigo_error='P0420',
                    descripcion='Diagnóstico único', fecha=ahora - timedelta(hours=1),
                ),
                Diagnostico(
                    moto_id=moto_tres, taller_id=taller_id, codigo_error='P0100',
                    descripcion='Moto transferida', fecha=ahora,
                ),
            ])
            db.session.flush()
            db.session.get(Moto, moto_tres).transferida = True
            db.session.commit()

        response = self.client.get('/prioridades', headers=self.headers(owner))
        self.assertEqual(response.status_code, 200, response.get_json())
        datos = {item['moto_id']: item for item in response.get_json()}
        self.assertEqual(set(datos), {moto_uno, moto_dos})
        self.assertEqual(datos[moto_uno]['codigo_error'], 'P0171')

    def test_motos_usa_la_ultima_orden_sin_cargar_el_historial(self):
        owner, taller_id = self.crear_taller()
        cliente = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(cliente)
        with app.app_context():
            ahora = datetime.now(timezone.utc)
            db.session.add_all([
                OrdenServicio(
                    numero='OS-1', secuencia=1, moto_id=moto_id, taller_id=taller_id,
                    descripcion='Orden antigua', estado='recibida',
                    creada_en=ahora - timedelta(days=2),
                    actualizada_en=ahora - timedelta(days=2),
                ),
                OrdenServicio(
                    numero='OS-2', secuencia=2, moto_id=moto_id, taller_id=taller_id,
                    descripcion='Orden reciente', estado='reparacion',
                    creada_en=ahora - timedelta(days=1), actualizada_en=ahora,
                ),
            ])
            db.session.commit()

        listado = self.client.get(
            '/motos?page=1&per_page=10', headers=self.headers(owner),
        )
        self.assertEqual(listado.status_code, 200, listado.get_json())
        moto = next(
            item for item in listado.get_json()['items'] if item['id'] == moto_id
        )
        self.assertEqual(moto['trabajo_actual']['numero'], 'OS-2')
        self.assertEqual(moto['trabajo_actual']['estado'], 'reparacion')

        detalle = self.client.get(
            '/motos/detalle?page=1&per_page=10', headers=self.headers(owner),
        )
        self.assertEqual(detalle.status_code, 200, detalle.get_json())
        moto = next(
            item for item in detalle.get_json()['items'] if item['id'] == moto_id
        )
        self.assertEqual(moto['cliente']['email'], 'cliente-prod@example.com')
        self.assertEqual(moto['trabajo_actual']['numero'], 'OS-2')

    def test_clientes_detalle_solo_carga_citas_desde_hoy(self):
        owner, taller_id = self.crear_taller()
        cliente = self.registrar_cliente(taller_id=taller_id)
        moto_id = self.crear_moto(cliente)
        with app.app_context():
            hoy = date.today()
            db.session.add_all([
                Cita(
                    moto_id=moto_id, taller_id=taller_id,
                    fecha=hoy - timedelta(days=3), descripcion='Pasada',
                ),
                Cita(
                    moto_id=moto_id, taller_id=taller_id,
                    fecha=hoy, descripcion='Hoy',
                ),
                Cita(
                    moto_id=moto_id, taller_id=taller_id,
                    fecha=hoy + timedelta(days=2), descripcion='Próxima',
                ),
            ])
            db.session.commit()

        response = self.client.get(
            '/clientes/detalle?page=1&per_page=10', headers=self.headers(owner),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        detalle = next(
            item for item in response.get_json()['items']
            if item['email'] == 'cliente-prod@example.com'
        )
        citas = detalle['motos'][0]['citas']
        self.assertEqual(
            [cita['descripcion'] for cita in citas], ['Hoy', 'Próxima']
        )


class PaginacionLimitesTests(BaseProduccionTests):
    def test_per_page_se_limita_a_doscientos_y_total_es_opcional(self):
        owner, _ = self.crear_taller()
        for indice in range(3):
            self.client.post('/inventario', headers=self.headers(owner), json={
                'nombre': f'Item {indice}', 'categoria': 'repuesto',
                'unidad': 'unidades', 'cantidad': 1, 'stock_minimo': 0,
            })

        pagina = self.client.get(
            '/inventario?page=1&per_page=999', headers=self.headers(owner),
        ).get_json()
        self.assertEqual(pagina['per_page'], 200)
        self.assertEqual(pagina['total'], 3)

        sin_total = self.client.get(
            '/inventario?page=1&per_page=2&total=0', headers=self.headers(owner),
        ).get_json()
        self.assertIsNone(sin_total['total'])
        self.assertIsNone(sin_total['pages'])
        self.assertEqual(len(sin_total['items']), 2)


class RetencionLotesTests(BaseProduccionTests):
    def test_retencion_borra_auditoria_en_varios_lotes(self):
        _, taller_id = self.crear_taller()
        with app.app_context():
            ahora = datetime.now(timezone.utc)
            db.session.bulk_save_objects([
                Auditoria(
                    entidad='prueba', accion='lote', taller_id=taller_id,
                    creada_en=ahora - timedelta(days=900),
                )
                for _ in range(150)
            ])
            db.session.commit()
            anterior = app.config.get('MOTOSMART_RETENCION_LOTE')
            app.config['MOTOSMART_RETENCION_LOTE'] = 100
            try:
                resumen = aplicar_retencion(dias_auditoria=30)
            finally:
                app.config['MOTOSMART_RETENCION_LOTE'] = anterior
            self.assertEqual(resumen['auditoria'], 150)
            self.assertEqual(Auditoria.query.filter_by(accion='lote').count(), 0)


class MigracionesTests(unittest.TestCase):
    def test_alembic_crea_el_esquema_completo_en_sqlite(self):
        try:
            import alembic  # noqa: F401
        except ImportError:
            self.skipTest('Alembic no está instalado en este entorno.')
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / 'migraciones.db'
            entorno = os.environ.copy()
            entorno['MOTOSMART_DATABASE_URL'] = f'sqlite:///{ruta.as_posix()}'
            entorno['MOTOSMART_JWT_SECRET_KEY'] = 'test-only-key-with-at-least-32-characters'
            resultado = subprocess.run(
                [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                cwd=PROJECT_ROOT, env=entorno, capture_output=True, text=True,
            )
            self.assertEqual(resultado.returncode, 0, resultado.stderr)
            conexion = sqlite3.connect(ruta)
            tablas = {
                fila[0] for fila in conexion.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            indices = {
                fila[0] for fila in conexion.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
            conexion.close()
            self.assertIn('talleres', tablas)
            self.assertIn('facturas', tablas)
            self.assertIn('trabajos_ocr', tablas)
            self.assertIn('alembic_version', tablas)
            for nuevo in (
                'ix_clientes_taller_nombre',
                'ix_diagnosticos_taller_moto_fecha',
                'ix_ordenes_taller_actualizada',
                'ix_registros_pendientes_expira',
                'ix_trabajos_ocr_estado_actualizado',
            ):
                self.assertIn(nuevo, indices)
            for redundante in (
                'ix_citas_taller_id',
                'ix_citas_moto_id',
                'ix_diagnosticos_taller_id',
                'ix_facturas_taller_id',
                'ix_ordenes_servicio_taller_id',
                'ix_usuarios_taller_id',
                'ix_inventario_taller_id',
                'ix_trabajos_ocr_taller_id',
                'ix_motos_taller_id',
                'ix_registros_pendientes_email',
                'ix_clientes_taller_id',
            ):
                self.assertNotIn(redundante, indices)
