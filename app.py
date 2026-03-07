import os
import shutil
from datetime import datetime
from flask import Flask
from flask_login import LoginManager
from config import Config
from models import db, Usuario, Categoria, registrar_auditoria
import pytz

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Por favor inicia sesión para acceder.'
    login_manager.login_message_category = 'warning'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return Usuario.query.get(int(user_id))

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

    # Context processor: notificaciones no leídas para el sidebar
    @app.context_processor
    def inject_notificaciones():
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                from models import Notificacion, CierreCaja
                count = Notificacion.query.filter_by(
                    destinatario_id=current_user.id, leido=False
                ).count()
                return {'notif_no_leidas': count}
        except:
            pass
        return {'notif_no_leidas': 0}

    return app


def init_db(app):
    with app.app_context():
        db.create_all()

        # Admin
        admin = Usuario.query.filter_by(username=app.config['ADMIN_USERNAME']).first()
        if not admin:
            admin = Usuario(
                username=app.config['ADMIN_USERNAME'],
                nombre_completo='Administrador',
                rol='administrador', activo=True
            )
            admin.set_password(app.config['ADMIN_PASSWORD'])
            db.session.add(admin)
            print(f"✅ Usuario admin creado: {app.config['ADMIN_USERNAME']}")

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

        db.session.commit()

        # Seed inventario de bienes físicos
        try:
            from routes.bienes import seed_bienes
            seed_bienes()
        except Exception as e:
            print(f"  Aviso seed bienes: {e}")

        print("✅ Base de datos inicializada.")


def hacer_backup(app):
    db_path = 'restaurante_pro.db'
    if not os.path.exists(db_path):
        return
    os.makedirs('backups', exist_ok=True)
    peru_tz = pytz.timezone('America/Lima')
    ahora = datetime.now(peru_tz)
    backup_name = f"backups/restaurante_pro_{ahora.strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(db_path, backup_name)
    backups = sorted([f for f in os.listdir('backups') if f.endswith('.db')])
    while len(backups) > 10:
        os.remove(os.path.join('backups', backups.pop(0)))
    print(f"✅ Backup: {backup_name}")


if __name__ == '__main__':
    app = create_app()
    init_db(app)
    hacer_backup(app)

    host = app.config['FLASK_HOST']
    port = app.config['FLASK_PORT']

    print("\n" + "="*55)
    print("🍽️  RESTOPRO v2.0")
    print("="*55)
    print(f"📍 Local:     http://localhost:{port}")
    print(f"📡 Red WiFi:  http://<TU_IP>:{port}")
    print(f"👤 Admin:     {app.config['ADMIN_USERNAME']}")
    print("="*55 + "\n")

    app.run(host=host, port=port, debug=False)
