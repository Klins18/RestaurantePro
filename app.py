import os
import secrets
import hmac
from datetime import datetime
from flask import Flask, abort, request, session
from flask_login import LoginManager
from flask_migrate import Migrate
from config import Config
from models import db, Usuario, Categoria, registrar_auditoria
import pytz

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    clave = app.config.get('SECRET_KEY')
    if not clave or len(clave) < 32 or clave in {
        'dev-secret-key-change-in-production',
        'tu-clave-super-secreta-cambiar-esto',
    }:
        raise RuntimeError('Configura una SECRET_KEY aleatoria de al menos 32 caracteres antes de iniciar la aplicación.')

    db.init_app(app)
    Migrate(app, db)

    @app.before_request
    def protect_state_changes():
        if request.path.startswith('/static/uploads/'):
            abort(404)
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            sent = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
            expected = session.get('_csrf_token')
            if not sent or not expected or not hmac.compare_digest(str(sent), str(expected)):
                abort(400, description='Token de seguridad inválido o vencido. Recarga la página e inténtalo de nuevo.')

    @app.context_processor
    def inject_csrf_token():
        def csrf_token():
            token = session.get('_csrf_token')
            if not token:
                token = secrets.token_urlsafe(32)
                session['_csrf_token'] = token
            return token
        return {'csrf_token': csrf_token}

    @app.context_processor
    def inject_permission_check():
        from routes.decorators import tiene_permiso
        return {'tiene_permiso': tiene_permiso}

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        return response

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Por favor inicia sesión para acceder.'
    login_manager.login_message_category = 'warning'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        usuario = db.session.get(Usuario, int(user_id))
        return usuario if usuario and usuario.activo else None

    # Blueprints
    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.pedidos import pedidos_bp
    from routes.almacen import almacen_bp
    from routes.admin import admin_bp
    from routes.kardex import kardex_bp
    from routes.compras import compras_bp
    from routes.ventas import ventas_bp
    from routes.empleados import empleados_bp
    from routes.bienes import bienes_bp
    from routes.pasajeros import pasajeros_bp
    from routes.suministros import suministros_bp
    from routes.operaciones import operaciones_bp
    from routes.reportes import reportes_bp
    from routes.cocina import cocina_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(pedidos_bp)
    app.register_blueprint(almacen_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(kardex_bp)
    app.register_blueprint(compras_bp)
    app.register_blueprint(ventas_bp)
    app.register_blueprint(empleados_bp)
    app.register_blueprint(bienes_bp)
    app.register_blueprint(pasajeros_bp)
    app.register_blueprint(suministros_bp)
    app.register_blueprint(operaciones_bp)
    app.register_blueprint(reportes_bp)
    app.register_blueprint(cocina_bp)

    # Context processor: notificaciones no leídas para el sidebar
    @app.context_processor
    def inject_notificaciones():
        try:
            from flask_login import current_user
            from flask import session, request as req
            if current_user and current_user.is_authenticated:
                from models import Notificacion
                # Refrescar solo en rutas de notificaciones o cada 10 requests
                cache_key = f'notif_count_{current_user.id}'
                req_count_key = f'notif_req_{current_user.id}'
                hits = session.get(req_count_key, 0)
                if hits == 0 or 'notificaciones' in req.path:
                    count = Notificacion.query.filter_by(
                        destinatario_id=current_user.id, leido=False
                    ).count()
                    session[cache_key] = count
                    session[req_count_key] = 10  # refrescar en 10 requests
                else:
                    session[req_count_key] = hits - 1
                    count = session.get(cache_key, 0)
                return {'notif_no_leidas': count}
        except:
            pass
        return {'notif_no_leidas': 0}

    return app


def init_db(app):
    with app.app_context():
        db.create_all()
        # create_all no altera índices en tablas existentes: materialízalos tras actualizar el modelo.
        for tabla in db.metadata.sorted_tables:
            for indice in tabla.indexes:
                indice.create(bind=db.engine, checkfirst=True)

        # Añade el costo opcional a inventarios físicos ya existentes.
        from sqlalchemy import inspect
        columnas_bienes = {col['name'] for col in inspect(db.engine).get_columns('bienes')}
        if 'costo_unitario' not in columnas_bienes:
            with db.engine.begin() as conexion:
                conexion.exec_driver_sql(
                    'ALTER TABLE bienes ADD COLUMN costo_unitario FLOAT NULL'
                )

        columnas_productos = {col['name'] for col in inspect(db.engine).get_columns('productos')}
        if 'costo_unitario' not in columnas_productos:
            with db.engine.begin() as conexion:
                conexion.exec_driver_sql(
                    'ALTER TABLE productos ADD COLUMN costo_unitario FLOAT NULL'
                )

        columnas_kardex = {col['name'] for col in inspect(db.engine).get_columns('kardex_almacen')}
        if 'costo_conocido' not in columnas_kardex:
            with db.engine.begin() as conexion:
                conexion.exec_driver_sql(
                    'ALTER TABLE kardex_almacen ADD COLUMN costo_conocido BOOLEAN NOT NULL DEFAULT 1'
                )

        from services.kardex import crear_saldos_iniciales
        crear_saldos_iniciales()

        # Recupera el último costo conocido desde las compras históricas.
        from models import ItemCompra, Compra, Producto
        for producto in Producto.query.filter(Producto.costo_unitario.is_(None)).all():
            ultima_compra = ItemCompra.query.join(Compra).filter(
                ItemCompra.producto_id == producto.id,
                ItemCompra.precio_unitario > 0,
                Compra.estado != 'anulado',
            ).order_by(Compra.fecha.desc(), Compra.id.desc(), ItemCompra.id.desc()).first()
            if ultima_compra:
                producto.costo_unitario = ultima_compra.precio_unitario
        db.session.commit()

        # Admin
        admin_username = app.config.get('ADMIN_USERNAME')
        admin_password = app.config.get('ADMIN_PASSWORD')
        if not admin_username:
            raise RuntimeError('Define ADMIN_USERNAME antes de inicializar la base.')
        admin = Usuario.query.filter_by(username=admin_username).first()
        if not admin:
            if not admin_password or len(admin_password) < 8:
                raise RuntimeError('Para crear el primer administrador, define ADMIN_PASSWORD con al menos 8 caracteres.')
            admin = Usuario(
                username=admin_username,
                nombre_completo='Administrador',
                rol='administrador', activo=True
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            print(f"Usuario administrador creado: {admin_username}")

        # Categorías almacén
        for nombre in ['Verdura Fresca','Frutas / Bombonera','Carnes',
                        'Abarrotes e Insumos de Limpieza','Lácteos y Derivados','Bebidas']:
            from models import Categoria
            if not Categoria.query.filter_by(nombre=nombre).first():
                db.session.add(Categoria(nombre=nombre))

        # Empresas turísticas (unificadas sin ruta)
        from models import EmpresaTuristica
        empresas_default = [
            ('Avalos Tours', '#6366f1'),
            ('Inka Express', '#f59e0b'),
            ('Peru Hop', '#10b981'),
            ('Privado', '#64748b'),
        ]
        for nombre, color in empresas_default:
            if not EmpresaTuristica.query.filter_by(nombre=nombre).first():
                db.session.add(EmpresaTuristica(nombre=nombre, ruta='', color=color))

        # Carta de bebidas
        from models import CategoriaCarta, ProductoCarta, VarianteCarta
        carta_default = {
            'Bebidas': [
                ('Gaseosa 600ml', 7.00, True,
                 ['Coca Cola', 'Inka Cola', 'Fanta', 'Sprite']),
                ('Gaseosa 300ml', 5.00, True,
                 ['Coca Cola Zero', 'Inka Cola Zero']),
                ('Agua Mineral', 5.00, True,
                 ['Con Gas', 'Sin Gas']),
                ('Cerveza Pequeña', 10.00, True,
                 ['Cusqueña Dorada', 'Cusqueña Trigo', 'Cusqueña Negra']),
                ('Cerveza Lata (Pilsen)', 13.00, False, []),
            ],
            'Jugos': [
                ('Zumo de Naranja', 10.00, False, []),
                ('Limonada', 10.00, False, []),
                ('Chicha Morada', 10.00, False, []),
                ('Jugo de Papaya', 9.00, False, []),
                ('Jugo de Piña', 10.00, False, []),
                ('Refresco de Maracuyá', 10.00, False, []),
            ],
            'Cafés': [
                ('Americano', 12.00, False, []),
                ('Expresso', 12.00, False, []),
                ('Cappuccino', 14.00, False, []),
            ],
        }
        orden_cat = 0
        for cat_nombre, productos in carta_default.items():
            cat = CategoriaCarta.query.filter_by(nombre=cat_nombre).first()
            if not cat:
                cat = CategoriaCarta(nombre=cat_nombre, orden=orden_cat)
                db.session.add(cat)
                db.session.flush()
            orden_cat += 1
            orden_prod = 0
            for prod_data in productos:
                nombre_prod, precio, tiene_var, variantes = prod_data
                if not ProductoCarta.query.filter_by(nombre=nombre_prod, categoria_id=cat.id).first():
                    prod = ProductoCarta(
                        categoria_id=cat.id, nombre=nombre_prod,
                        precio=precio, tiene_variantes=tiene_var, orden=orden_prod
                    )
                    db.session.add(prod)
                    db.session.flush()
                    for v_nombre in variantes:
                        db.session.add(VarianteCarta(producto_id=prod.id, nombre=v_nombre))
                orden_prod += 1

        # Las bebidas envasadas deben existir también en almacén y descontar
        # stock al venderse. Sin esta relación, la venta puede aprobarse aunque
        # el inventario esté en cero. Jugos y bebidas preparadas no se incluyen:
        # su control requiere registrar sus insumos/recetas.
        bebidas_control_stock = {
            'Gaseosa 600ml', 'Gaseosa 300ml', 'Agua Mineral',
            'Cerveza Pequeña', 'Cerveza Lata (Pilsen)',
        }
        categoria_bebidas = Categoria.query.filter_by(nombre='Bebidas').first()
        for nombre_producto in bebidas_control_stock:
            producto_carta = ProductoCarta.query.filter_by(nombre=nombre_producto).first()
            if not producto_carta:
                continue
            producto_almacen = Producto.query.filter(
                db.func.lower(db.func.trim(Producto.nombre)) == nombre_producto.lower()
            ).first()
            if not producto_almacen:
                producto_almacen = Producto(
                    nombre=nombre_producto,
                    unidad_medida='unidad',
                    categoria_id=categoria_bebidas.id if categoria_bebidas else None,
                    stock_actual=0,
                    stock_minimo=0,
                    activo=True,
                )
                db.session.add(producto_almacen)
                db.session.flush()
            producto_carta.descuenta_inventario = True
            producto_carta.producto_almacen_id = producto_almacen.id

        db.session.commit()

        # Seed inventario de bienes físicos
        try:
            from routes.bienes import seed_bienes
            seed_bienes()
        except Exception as e:
            db.session.rollback()
            print(f"  Aviso seed bienes: {e}")

        print("Base de datos inicializada.")


def hacer_backup(app):
    from sqlalchemy.engine import make_url
    with app.app_context():
        url = make_url(db.engine.url)
        if not url.drivername.startswith('sqlite') or url.database in (None, ':memory:'):
            app.logger.warning('Backup local omitido: la base configurada no es un archivo SQLite.')
            return None
        db_path = os.path.abspath(url.database)
        if not os.path.isfile(db_path):
            app.logger.warning('No existe el archivo de base de datos para respaldar: %s', db_path)
            return None
        backup_dir = os.path.join(app.instance_path, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        ahora = datetime.now(pytz.timezone('America/Lima'))
        backup_name = os.path.join(backup_dir, f"restaurante_pro_{ahora.strftime('%Y%m%d_%H%M%S_%f')}.db")
        source = db.engine.raw_connection()
        target = None
        try:
            import sqlite3
            target = sqlite3.connect(backup_name)
            source.backup(target)
        finally:
            if target is not None:
                target.close()
            source.close()
        backups = sorted(
            os.path.join(backup_dir, name) for name in os.listdir(backup_dir)
            if name.endswith('.db')
        )
        while len(backups) > 10:
            os.remove(backups.pop(0))
        app.logger.info('Backup SQLite creado: %s', backup_name)
        return backup_name


app = create_app()


if __name__ == '__main__':
    init_db(app)
    hacer_backup(app)

    host = app.config['FLASK_HOST']
    port = app.config['FLASK_PORT']

    print("\n" + "="*55)
    print("RESTOPRO v2.0")
    print("="*55)
    print(f"Local:       http://localhost:{port}")
    print(f"Red WiFi:    http://<TU_IP>:{port}")
    print(f"Admin:       {app.config['ADMIN_USERNAME']}")
    print("="*55 + "\n")

    app.run(host=host, port=port, debug=False)
