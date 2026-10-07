"""Pruebas de integración con una base SQLite aislada en memoria."""
import json
import os
import re
import unittest
from datetime import date, datetime

os.environ['DATABASE_URL'] = 'sqlite://'

from app import create_app, init_db
from models import (
    BalonGas,
    Categoria,
    CategoriaBien,
    CategoriaCarta,
    Compra,
    CierreCaja,
    Auditoria,
    Bien,
    ItemPedido,
    ItemCompra,
    KardexBienes,
    KardexAlmacen,
    ListaPedido,
    MovimientoAlmacen,
    Producto,
    ProductoCarta,
    SolicitudVenta,
    Usuario,
    VentaDiaria,
    db,
)
from services.units import normalize_unit


class ProductionScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app({
            'TESTING': True,
            'SECRET_KEY': 'test-key-that-is-not-used-outside-this-suite',
            'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'ADMIN_USERNAME': 'qa_admin',
            'ADMIN_PASSWORD': 'qa-password-123456',
        })
        init_db(cls.app)
        with cls.app.app_context():
            cls.admin_id = Usuario.query.filter_by(username='qa_admin').one().id

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def setUp(self):
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.admin_id)
            session['_fresh'] = True
            session['_csrf_token'] = 'qa-csrf-token'

    def post(self, path, **data):
        return self.client.post(path, data={'csrf_token': 'qa-csrf-token', **data})

    def test_measurement_unit_aliases_share_one_canonical_value(self):
        for alias, canonical in (
            (' KILO ', 'kg'), ('kilogramos', 'kg'), ('GRAMOS', 'g'),
            ('Litros', 'l'), ('UNID', 'unidad'), ('panes', 'pan'),
            ('PQT', 'paquete'), ('@', 'arroba'),
        ):
            with self.subTest(alias=alias):
                self.assertEqual(normalize_unit(alias), canonical)

    def test_all_get_routes_and_invalid_filters_have_no_server_errors(self):
        bad_query = (
            '?desde=bad&hasta=2026-99-99&fecha=bad&mes=99&anio=NaN&page=-4'
            '&categoria=abc&producto=NaN&producto_id=Infinity&bien_id=bad'
            '&area=%FF&empleado_id=oops&tipo=__invalid__'
        )
        for rule in self.app.url_map.iter_rules():
            if 'GET' not in rule.methods or rule.endpoint == 'static':
                continue
            path = re.sub(
                r'<(?:[^:<>]+:)?([^<>]+)>',
                lambda match: '999999' if 'int' in match.group(0) else 'test-file',
                rule.rule,
            )
            for suffix in ('', bad_query):
                with self.subTest(endpoint=rule.endpoint, query=bool(suffix)):
                    response = self.client.get(path + suffix)
                    self.assertLess(response.status_code, 500)

    def test_empty_post_payloads_never_raise_server_errors(self):
        for rule in self.app.url_map.iter_rules():
            if 'POST' not in rule.methods or rule.endpoint in {'static', 'auth.logout'}:
                continue
            path = re.sub(
                r'<(?:[^:<>]+:)?([^<>]+)>',
                lambda match: '999999' if 'int' in match.group(0) else 'test-file',
                rule.rule,
            )
            with self.subTest(endpoint=rule.endpoint):
                response = self.client.post(path, data={'csrf_token': 'qa-csrf-token'})
                self.assertLess(response.status_code, 500)
                with self.app.app_context():
                    db.session.rollback()

    def test_mutations_require_csrf(self):
        response = self.client.post('/almacen/ingreso', data={'cantidad': '1'})
        self.assertEqual(response.status_code, 400)

    def test_inventory_rejects_non_finite_values_and_prevents_negative_stock(self):
        with self.app.app_context():
            category = Categoria.query.filter_by(nombre='Carnes').one()
            product = Producto(
                nombre='QA stock flow', unidad_medida='kg', categoria_id=category.id,
                stock_actual=0, stock_minimo=1, activo=True,
            )
            db.session.add(product)
            db.session.commit()
            product_id = product.id

        response = self.post(
            '/almacen/ingreso', producto_id=product_id, cantidad='2.5',
            costo_unitario='4.20', motivo='Prueba de recepción', referencia='QA-IN',
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertAlmostEqual(db.session.get(Producto, product_id).stock_actual, 2.5)

        for path, field, value in (
            ('/almacen/ingreso', 'cantidad', 'NaN'),
            ('/almacen/ingreso', 'costo_unitario', 'Infinity'),
            ('/almacen/egreso', 'cantidad', 'Infinity'),
        ):
            with self.subTest(field=field, value=value):
                response = self.post(path, producto_id=product_id, **{field: value})
                self.assertEqual(response.status_code, 302)

        response = self.post('/almacen/egreso', producto_id=product_id, cantidad='3')
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertAlmostEqual(db.session.get(Producto, product_id).stock_actual, 2.5)
            rows = KardexAlmacen.query.filter_by(producto_id=product_id).all()
            self.assertEqual(len(rows), 1)
            self.assertAlmostEqual(rows[0].cant_saldo, 2.5)

    def test_goods_can_be_added_to_an_area_with_a_new_category(self):
        response = self.post(
            '/bienes/nuevo', area='COCINA', categoria_id='__new__',
            nueva_categoria='Electrodomésticos', nombre='Licuadora nueva QA',
            estado_bueno='1', estado_malo='0', total='1', costo_unitario='350',
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            bien = Bien.query.filter_by(nombre='Licuadora nueva QA', area='COCINA').one()
            self.assertEqual(bien.categoria.nombre, 'Electrodomésticos')
            self.assertEqual(bien.total, 1)
            self.assertEqual(bien.costo_unitario, 350)
            self.assertEqual(KardexBienes.query.filter_by(bien_id=bien.id).count(), 1)

        form = self.client.get('/bienes/nuevo?area=COCINA')
        self.assertEqual(form.status_code, 200)
        self.assertIn('Electrodomésticos', form.get_data(as_text=True))
        listing = self.client.get('/bienes/?area=COCINA')
        self.assertIn('Licuadora nueva QA', listing.get_data(as_text=True))

    def test_goods_can_be_reclassified_while_editing(self):
        with self.app.app_context():
            area_category = CategoriaBien.query.filter_by(nombre='Equipos', area='COCINA').one()
            bien = Bien(
                nombre='Equipo QA', area='COCINA', categoria_id=area_category.id,
                estado_bueno=1, estado_malo=0, total=1,
            )
            db.session.add(bien)
            db.session.commit()
            bien_id = bien.id

        response = self.post(
            f'/bienes/{bien_id}/editar', area='COCINA', categoria_id='__new__',
            nueva_categoria='Electrodomésticos', nombre='Licuadora QA',
            estado_bueno='1', estado_malo='0', total='1', costo_unitario='',
            observaciones='',
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            bien = db.session.get(Bien, bien_id)
            self.assertEqual(bien.nombre, 'Licuadora QA')
            self.assertEqual(bien.categoria.nombre, 'Electrodomésticos')

    def test_duplicate_inventory_product_is_rejected(self):
        payload = {
            'nombre': 'Producto único QA', 'unidad_medida': 'unidad',
            'categoria_id': '', 'stock_minimo': '0', 'costo_unitario': '',
        }
        self.assertEqual(self.post('/admin/productos/nuevo', **payload).status_code, 302)
        self.assertEqual(self.post('/admin/productos/nuevo', **payload).status_code, 302)
        with self.app.app_context():
            self.assertEqual(Producto.query.filter_by(nombre='Producto único QA', activo=True).count(), 1)

    def test_purchase_and_order_receipt_update_stock_once(self):
        with self.app.app_context():
            category = Categoria.query.filter_by(nombre='Abarrotes e Insumos de Limpieza').one()
            product = Producto(
                nombre='QA compra', unidad_medida='kg', categoria_id=category.id,
                stock_actual=0, stock_minimo=0, activo=True,
            )
            db.session.add(product)
            db.session.commit()
            product_id = product.id

        response = self.post(
            '/compras/nueva', fecha='2026-10-07', proveedor_nombre='QA proveedor',
            tipo_comprobante='factura', serie_comprobante='F001',
            numero_comprobante='QA-01', tipo_pago='efectivo', igv='0',
            **{
                'item_desc[]': 'Arroz QA', 'item_cant[]': '4', 'item_unidad[]': 'Kilo',
                'item_precio[]': '5.25', 'item_producto_id[]': str(product_id),
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            purchase = Compra.query.order_by(Compra.id.desc()).first()
            purchase_id = purchase.id
            self.assertEqual(ItemCompra.query.filter_by(compra_id=purchase.id).one().unidad, 'kg')
            self.assertAlmostEqual(db.session.get(Producto, product_id).stock_actual, 4)

        response = self.post(f'/compras/{purchase_id}/anular')
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertAlmostEqual(db.session.get(Producto, product_id).stock_actual, 0)

        response = self.post(
            '/pedidos/nueva', titulo='QA pedido', tipo_requerimiento='QA', fecha='2026-10-07',
            **{
                'item_nombre[]': 'Producto recibido QA', 'item_unidad[]': 'kg',
                'item_cantidad[]': '3', 'item_precio[]': '2.75', 'item_obs[]': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            order = ListaPedido.query.order_by(ListaPedido.id.desc()).first()
            order_id = order.id
            item = ItemPedido.query.filter_by(lista_id=order_id).one()
            item_id = item.id
        payload = {
            f'check_{item_id}': 'on', f'cant_{item_id}': '3',
            f'precio_{item_id}': '2.75', f'obs_{item_id}': '',
        }
        self.assertEqual(self.post(f'/pedidos/{order_id}/verificar', **payload).status_code, 302)
        with self.app.app_context():
            item = db.session.get(ItemPedido, item_id)
            received_product_id = item.producto_id
            self.assertAlmostEqual(db.session.get(Producto, received_product_id).stock_actual, 3)
            self.assertEqual(MovimientoAlmacen.query.filter_by(lista_pedido_id=order_id).count(), 1)
        self.assertEqual(self.post(f'/pedidos/{order_id}/verificar', **payload).status_code, 302)
        with self.app.app_context():
            self.assertAlmostEqual(db.session.get(Producto, received_product_id).stock_actual, 3)
        self.assertEqual(self.post(f'/pedidos/{order_id}/aprobar').status_code, 302)

    def test_purchase_with_igv_included_keeps_the_entered_total(self):
        response = self.post(
            '/compras/nueva', fecha='2026-10-07', proveedor_nombre='Proveedor IGV QA',
            tipo_comprobante='factura', tipo_pago='efectivo', igv='18',
            **{
                'item_desc[]': 'Producto con IGV incluido', 'item_cant[]': '1',
                'item_unidad[]': 'unidad', 'item_precio[]': '118',
                'item_producto_id[]': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            compra = Compra.query.filter_by(proveedor_nombre='Proveedor IGV QA').one()
            self.assertAlmostEqual(compra.subtotal, 100)
            self.assertAlmostEqual(compra.igv, 18)
            self.assertAlmostEqual(compra.total, 118)

    def test_accidental_cash_close_can_be_reopened_and_closed_again_with_audit(self):
        fecha = '2026-10-05'
        cierre_payload = {
            'fecha': fecha, 'efectivo': '0', 'tarjeta': '0',
            'yape': '0', 'transferencia': '0', 'observaciones': '',
        }
        self.assertEqual(self.post('/ventas/cierre', **cierre_payload).status_code, 302)
        with self.app.app_context():
            cierre = CierreCaja.query.filter_by(fecha=datetime.strptime(fecha, '%Y-%m-%d').date()).one()
            cierre_id = cierre.id
            self.assertFalse(cierre.abierta)

        sale = [{
            'num_pax': 1, 'precio_buffet': 35, 'es_privado': False,
            'nombre_grupo': '', 'tipo_pago': '', 'items': [],
        }]
        sale_token = 'a' * 32
        blocked = self.post('/ventas/nueva', fecha=fecha, tabs_json=json.dumps(sale), solicitud_token=sale_token)
        self.assertEqual(blocked.status_code, 302)
        with self.app.app_context():
            self.assertEqual(VentaDiaria.query.filter_by(fecha=datetime.strptime(fecha, '%Y-%m-%d').date()).count(), 0)

        self.post(f'/ventas/cierre/{cierre_id}/reabrir', motivo='No')
        with self.app.app_context():
            self.assertFalse(db.session.get(CierreCaja, cierre_id).abierta)
            employee = Usuario(username='qa_cash_employee', nombre_completo='QA Cash Employee', rol='empleado', activo=True)
            employee.set_password('qa-password-123456')
            db.session.add(employee)
            db.session.commit()
            employee_id = employee.id
        with self.client.session_transaction() as session:
            session['_user_id'] = str(employee_id)
            session['_fresh'] = True
        self.post(f'/ventas/cierre/{cierre_id}/reabrir', motivo='Intento de empleado no autorizado')
        with self.app.app_context():
            self.assertFalse(db.session.get(CierreCaja, cierre_id).abierta)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.admin_id)
            session['_fresh'] = True

        self.assertEqual(self.post(f'/ventas/cierre/{cierre_id}/reabrir', motivo='Cierre por error antes de registrar venta.').status_code, 302)
        with self.app.app_context():
            cierre = db.session.get(CierreCaja, cierre_id)
            self.assertTrue(cierre.abierta)
            self.assertEqual(cierre.motivo_reapertura, 'Cierre por error antes de registrar venta.')
            self.assertEqual(Auditoria.query.filter_by(accion='REABRIR_CAJA', registro_id=cierre_id).count(), 1)

        self.assertEqual(self.post('/ventas/nueva', fecha=fecha, tabs_json=json.dumps(sale), solicitud_token=sale_token).status_code, 302)
        cierre_rehecho = dict(cierre_payload, efectivo='35')
        self.assertEqual(self.post('/ventas/cierre', **cierre_rehecho).status_code, 302)
        with self.app.app_context():
            cierre = db.session.get(CierreCaja, cierre_id)
            self.assertFalse(cierre.abierta)
            self.assertEqual(cierre.total_cobrado, 35)
            self.assertEqual(VentaDiaria.query.filter_by(fecha=cierre.fecha).count(), 1)
            self.assertEqual(Auditoria.query.filter_by(accion='RECIERRE_CAJA', registro_id=cierre_id).count(), 1)

    def test_sales_deduct_and_reversal_restore_linked_inventory(self):
        with self.app.app_context():
            category = Categoria.query.filter_by(nombre='Bebidas').one()
            menu_category = CategoriaCarta.query.filter_by(nombre='Bebidas').one()
            stock_product = Producto(
                nombre='QA bebida de stock', unidad_medida='unidad',
                categoria_id=category.id, stock_actual=3, stock_minimo=0,
                activo=True,
            )
            db.session.add(stock_product)
            db.session.flush()
            menu_product = ProductoCarta(
                nombre='QA bebida vendible', categoria_id=menu_category.id,
                precio=8.5, activo=True, descuenta_inventario=True,
                producto_almacen_id=stock_product.id,
            )
            db.session.add(menu_product)
            db.session.commit()
            stock_id, menu_id = stock_product.id, menu_product.id

        tabs = [{
            'num_pax': 2, 'precio_buffet': 35, 'es_privado': True,
            'nombre_grupo': 'QA venta', 'tipo_pago': 'efectivo',
            'items': [{'prod_id': menu_id, 'nombre': 'QA bebida vendible', 'cant': 1, 'precio': 8.5}],
        }]
        sale_token = 'b' * 32
        response = self.post('/ventas/nueva', fecha='2026-10-07', tabs_json=json.dumps(tabs), solicitud_token=sale_token)
        self.assertEqual(response.status_code, 302)
        # Si el navegador reintenta la petición tras perder la respuesta, se muestra
        # la venta existente y no se vuelve a descontar el inventario.
        repeated = self.post('/ventas/nueva', fecha='2026-10-07', tabs_json=json.dumps(tabs), solicitud_token=sale_token)
        self.assertEqual(repeated.status_code, 302)
        with self.app.app_context():
            sale = VentaDiaria.query.order_by(VentaDiaria.id.desc()).first()
            sale_id = sale.id
            self.assertAlmostEqual(sale.total, 78.5)
            self.assertEqual(VentaDiaria.query.filter_by(solicitud_id=sale.solicitud_id).count(), 1)
            self.assertEqual(SolicitudVenta.query.filter_by(token=sale_token).count(), 1)
            self.assertAlmostEqual(db.session.get(Producto, stock_id).stock_actual, 2)
        self.assertEqual(self.post(f'/ventas/{sale_id}/eliminar-venta').status_code, 302)
        with self.app.app_context():
            self.assertAlmostEqual(db.session.get(Producto, stock_id).stock_actual, 3)

    def test_sale_submission_rejects_empty_services_and_blank_items(self):
        fecha = '2026-10-04'
        token = 'c' * 32
        empty = [{'num_pax': 0, 'precio_buffet': 0, 'items': []}]
        self.assertEqual(self.post(
            '/ventas/nueva', fecha=fecha, solicitud_token=token,
            tabs_json=json.dumps(empty),
        ).status_code, 302)
        token = 'd' * 32
        blank_line = [{
            'num_pax': 0, 'precio_buffet': 0,
            'items': [{'nombre': ' ', 'cant': 1, 'precio': 5}],
        }]
        self.assertEqual(self.post(
            '/ventas/nueva', fecha=fecha, solicitud_token=token,
            tabs_json=json.dumps(blank_line),
        ).status_code, 302)
        with self.app.app_context():
            self.assertEqual(VentaDiaria.query.filter_by(fecha=datetime.strptime(fecha, '%Y-%m-%d').date()).count(), 0)
            self.assertEqual(SolicitudVenta.query.filter(SolicitudVenta.token.in_(['c' * 32, 'd' * 32])).count(), 0)

    def test_gas_moves_and_legacy_route_remain_usable(self):
        response = self.post(
            '/operaciones/gas', accion='nuevo', cantidad='1', precio_unitario='55.00',
            peso_kg='10', fecha_compra='2026-10-07', estado='disponible', proveedor='QA',
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            gas = BalonGas.query.order_by(BalonGas.id.desc()).first()
            gas_id = gas.id
        self.assertEqual(self.client.get('/operaciones/gas').status_code, 200)
        self.assertEqual(self.client.get('/pasajeros/gas').status_code, 301)
        response = self.post('/operaciones/gas', accion='usar', balon_id=gas_id)
        self.assertEqual(response.status_code, 302)
        fecha_inicio_original = date(2026, 10, 1)
        with self.app.app_context():
            gas = db.session.get(BalonGas, gas_id)
            gas.fecha_inicio = fecha_inicio_original
            db.session.commit()
        # Un envío repetido no reinicia la fecha de inicio del balón en uso.
        response = self.post('/operaciones/gas', accion='usar', balon_id=gas_id)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(BalonGas, gas_id).fecha_inicio, fecha_inicio_original)
        response = self.post('/operaciones/gas', accion='agotar', balon_id=gas_id)
        self.assertEqual(response.status_code, 302)
        response = self.post('/operaciones/gas', accion='usar', balon_id=gas_id)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(BalonGas, gas_id).estado, 'agotado')


if __name__ == '__main__':
    unittest.main()
