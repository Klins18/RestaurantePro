from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import pytz

db = SQLAlchemy()

PERU_TZ = pytz.timezone('America/Lima')

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

# ─────────────────────────────────────────
#  USUARIOS Y ROLES
# ─────────────────────────────────────────
class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    nombre_completo = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.String(30), nullable=False, default='empleado')
    # roles: administrador | empleado
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=now_peru)
    creado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def es_admin(self):
        return self.rol == 'administrador'

    def __repr__(self):
        return f'<Usuario {self.username}>'

# ─────────────────────────────────────────
#  CATEGORÍAS DE PRODUCTOS
# ─────────────────────────────────────────
class Categoria(db.Model):
    __tablename__ = 'categorias'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.String(255))
    activo = db.Column(db.Boolean, default=True)
    productos = db.relationship('Producto', backref='categoria', lazy=True)

# ─────────────────────────────────────────
#  PRODUCTOS DEL ALMACÉN
# ─────────────────────────────────────────
class Producto(db.Model):
    __tablename__ = 'productos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    unidad_medida = db.Column(db.String(30), nullable=False, default='unidad')
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=True)
    stock_actual = db.Column(db.Float, default=0)
    stock_minimo = db.Column(db.Float, default=0)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=now_peru)

    movimientos = db.relationship('MovimientoAlmacen', backref='producto', lazy=True)

# ─────────────────────────────────────────
#  PROVEEDORES
# ─────────────────────────────────────────
class Proveedor(db.Model):
    __tablename__ = 'proveedores'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    ruc = db.Column(db.String(11))
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(100))
    direccion = db.Column(db.String(255))
    activo = db.Column(db.Boolean, default=True)

# ─────────────────────────────────────────
#  LISTA DE PEDIDOS (como las fotos)
# ─────────────────────────────────────────
class ListaPedido(db.Model):
    __tablename__ = 'listas_pedido'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    tipo_requerimiento = db.Column(db.String(100))  # VERDURA FRESCA, CARNES, ABARROTES, etc.
    fecha = db.Column(db.Date, nullable=False)
    estado = db.Column(db.String(30), default='pendiente')
    # estados: pendiente | en_verificacion | completado | aprobado

    # Responsable que elaboró la lista
    elaborado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    elaborado_en = db.Column(db.DateTime, default=now_peru)

    # Responsable que verifica
    verificado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    verificado_en = db.Column(db.DateTime, nullable=True)

    # Aprobación del administrador
    aprobado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    aprobado_en = db.Column(db.DateTime, nullable=True)

    observaciones = db.Column(db.Text)

    elaborado_por = db.relationship('Usuario', foreign_keys=[elaborado_por_id])
    verificado_por = db.relationship('Usuario', foreign_keys=[verificado_por_id])
    aprobado_por = db.relationship('Usuario', foreign_keys=[aprobado_por_id])
    items = db.relationship('ItemPedido', backref='lista', lazy=True, cascade='all, delete-orphan')

# ─────────────────────────────────────────
#  ITEMS DE CADA LISTA DE PEDIDO
# ─────────────────────────────────────────
class ItemPedido(db.Model):
    __tablename__ = 'items_pedido'
    id = db.Column(db.Integer, primary_key=True)
    lista_id = db.Column(db.Integer, db.ForeignKey('listas_pedido.id'), nullable=False)
    producto_nombre = db.Column(db.String(150), nullable=False)  # Nombre libre como en las fotos
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=True)
    unidad_medida = db.Column(db.String(30))
    cantidad_solicitada = db.Column(db.Float)
    cantidad_recibida = db.Column(db.Float, nullable=True)
    precio_unitario = db.Column(db.Float, nullable=True)   # Precio unitario de mercado
    verificado = db.Column(db.Boolean, default=False)  # Check de verificación
    observacion = db.Column(db.String(255))
    orden = db.Column(db.Integer, default=0)

# ─────────────────────────────────────────
#  MOVIMIENTOS DE ALMACÉN (Ingresos/Egresos)
# ─────────────────────────────────────────
class MovimientoAlmacen(db.Model):
    __tablename__ = 'movimientos_almacen'
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)  # ingreso | egreso
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False)
    cantidad = db.Column(db.Float, nullable=False)
    unidad_medida = db.Column(db.String(30))
    motivo = db.Column(db.String(255))
    referencia = db.Column(db.String(100))  # N° factura, orden, etc.
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores.id'), nullable=True)
    lista_pedido_id = db.Column(db.Integer, db.ForeignKey('listas_pedido.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha_hora = db.Column(db.DateTime, default=now_peru)
    observaciones = db.Column(db.Text)

    usuario = db.relationship('Usuario', foreign_keys=[usuario_id])
    proveedor = db.relationship('Proveedor')

# ─────────────────────────────────────────
#  AUDITORÍA
# ─────────────────────────────────────────
class Auditoria(db.Model):
    __tablename__ = 'auditoria'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    accion = db.Column(db.String(100), nullable=False)
    tabla = db.Column(db.String(50))
    registro_id = db.Column(db.Integer)
    detalle = db.Column(db.Text)
    ip = db.Column(db.String(45))
    fecha_hora = db.Column(db.DateTime, default=now_peru)

    usuario = db.relationship('Usuario')

def registrar_auditoria(usuario_id, accion, tabla=None, registro_id=None, detalle=None, ip=None):
    entrada = Auditoria(
        usuario_id=usuario_id,
        accion=accion,
        tabla=tabla,
        registro_id=registro_id,
        detalle=detalle,
        ip=ip
    )
    db.session.add(entrada)

# ═══════════════════════════════════════════════════════════════
#  ENTREGA 1: KARDEX VALORIZADO + COMPRAS + VENTAS
# ═══════════════════════════════════════════════════════════════

# ─────────────────────────────────────────
#  KARDEX VALORIZADO (precio promedio ponderado)
# ─────────────────────────────────────────
class KardexAlmacen(db.Model):
    """Kardex valorizado para ALMACÉN (insumos y materia prima)"""
    __tablename__ = 'kardex_almacen'
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=now_peru)
    tipo = db.Column(db.String(10), nullable=False)        # ingreso | egreso | ajuste
    concepto = db.Column(db.String(200))                   # descripción del movimiento
    referencia = db.Column(db.String(100))                 # N° factura, orden, etc.

    # ENTRADA
    cant_entrada = db.Column(db.Float, default=0)
    precio_entrada = db.Column(db.Float, default=0)
    total_entrada = db.Column(db.Float, default=0)

    # SALIDA
    cant_salida = db.Column(db.Float, default=0)
    precio_salida = db.Column(db.Float, default=0)
    total_salida = db.Column(db.Float, default=0)

    # SALDO (acumulado)
    cant_saldo = db.Column(db.Float, default=0)
    precio_saldo = db.Column(db.Float, default=0)   # precio promedio ponderado
    total_saldo = db.Column(db.Float, default=0)

    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    compra_id = db.Column(db.Integer, db.ForeignKey('compras.id'), nullable=True)

    producto = db.relationship('Producto')
    usuario = db.relationship('Usuario')


class KardexComedor(db.Model):
    """Kardex valorizado para COMEDOR (productos de venta)"""
    __tablename__ = 'kardex_comedor'
    id = db.Column(db.Integer, primary_key=True)
    producto_carta_id = db.Column(db.Integer, db.ForeignKey('productos_carta.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=now_peru)
    tipo = db.Column(db.String(10), nullable=False)        # ingreso | egreso | venta

    concepto = db.Column(db.String(200))
    referencia = db.Column(db.String(100))

    cant_entrada = db.Column(db.Float, default=0)
    precio_entrada = db.Column(db.Float, default=0)
    total_entrada = db.Column(db.Float, default=0)

    cant_salida = db.Column(db.Float, default=0)
    precio_salida = db.Column(db.Float, default=0)
    total_salida = db.Column(db.Float, default=0)

    cant_saldo = db.Column(db.Float, default=0)
    precio_saldo = db.Column(db.Float, default=0)
    total_saldo = db.Column(db.Float, default=0)

    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))

    producto_carta = db.relationship('ProductoCarta')
    usuario = db.relationship('Usuario')


# ─────────────────────────────────────────
#  PRODUCTOS DE CARTA (para comedor y ventas)
# ─────────────────────────────────────────
class CategoriaCarta(db.Model):
    __tablename__ = 'categorias_carta'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)     # Bebidas, Jugos, Cafés, etc.
    orden = db.Column(db.Integer, default=0)
    activo = db.Column(db.Boolean, default=True)
    productos = db.relationship('ProductoCarta', backref='categoria_carta', lazy=True)


class ProductoCarta(db.Model):
    __tablename__ = 'productos_carta'
    id = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias_carta.id'), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.String(255))
    precio = db.Column(db.Float, nullable=False, default=0)
    tiene_variantes = db.Column(db.Boolean, default=False)
    activo = db.Column(db.Boolean, default=True)
    orden = db.Column(db.Integer, default=0)
    # Si True, descuenta del inventario almacén al venderse
    descuenta_inventario = db.Column(db.Boolean, default=False)
    # ID del producto en almacén vinculado (para descuento)
    producto_almacen_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=True)
    variantes = db.relationship('VarianteCarta', backref='producto', lazy=True, cascade='all, delete-orphan')


class VarianteCarta(db.Model):
    """Ej: CocaCola, Inka Cola, Fanta, Sprite (dentro de Gaseosa 600ml)"""
    __tablename__ = 'variantes_carta'
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos_carta.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)     # CocaCola, Inka Cola...
    activo = db.Column(db.Boolean, default=True)


# ─────────────────────────────────────────
#  EMPRESAS TURÍSTICAS
# ─────────────────────────────────────────
class EmpresaTuristica(db.Model):
    __tablename__ = 'empresas_turisticas'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)     # Avalos Tours, Inka Express...
    ruta = db.Column(db.String(50))                        # Cusco, Puno, (vacío para PeruHop)
    color = db.Column(db.String(20), default='#6366f1')    # color para gráficos
    activo = db.Column(db.Boolean, default=True)

    @property
    def nombre_completo(self):
        if self.ruta:
            return f"{self.nombre} ({self.ruta})"
        return self.nombre


# ─────────────────────────────────────────
#  REGISTRO DE COMPRAS
# ─────────────────────────────────────────
class Compra(db.Model):
    __tablename__ = 'compras'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores.id'), nullable=True)
    proveedor_nombre = db.Column(db.String(150))           # por si no está en BD

    # Comprobante
    tipo_comprobante = db.Column(db.String(30))            # factura | boleta | ticket | ninguno
    serie_comprobante = db.Column(db.String(20))           # F001, B001
    numero_comprobante = db.Column(db.String(30))          # 00001234
    archivo_comprobante = db.Column(db.String(255))        # ruta del PDF/imagen adjunta

    # Pago
    tipo_pago = db.Column(db.String(30))                   # efectivo | transferencia | tarjeta | credito
    fecha_pago = db.Column(db.Date, nullable=True)
    numero_operacion = db.Column(db.String(50))            # N° operación de transferencia

    # Totales
    subtotal = db.Column(db.Float, default=0)
    igv = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)

    observaciones = db.Column(db.Text)
    estado = db.Column(db.String(20), default='registrado')  # registrado | pagado | anulado

    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    creado_en = db.Column(db.DateTime, default=now_peru)

    proveedor = db.relationship('Proveedor')
    usuario = db.relationship('Usuario')
    items = db.relationship('ItemCompra', backref='compra', lazy=True, cascade='all, delete-orphan')


class ItemCompra(db.Model):
    __tablename__ = 'items_compra'
    id = db.Column(db.Integer, primary_key=True)
    compra_id = db.Column(db.Integer, db.ForeignKey('compras.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=True)
    descripcion = db.Column(db.String(200), nullable=False)
    cantidad = db.Column(db.Float, nullable=False)
    unidad = db.Column(db.String(30))
    precio_unitario = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)


# ─────────────────────────────────────────
#  REGISTRO DE VENTAS DIARIAS
# ─────────────────────────────────────────
class VentaDiaria(db.Model):
    """Cabecera de venta — un grupo o servicio del día"""
    __tablename__ = 'ventas_diarias'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas_turisticas.id'), nullable=True)
    tipo_cliente = db.Column(db.String(20), default='empresa')   # empresa | privado
    nombre_grupo = db.Column(db.String(150))                     # solo para grupos privados
    num_pax = db.Column(db.Integer, default=0)                   # pasajeros buffet
    ruta = db.Column(db.String(50))                              # Cusco-Puno, Puno-Cusco, etc.
    precio_buffet = db.Column(db.Float, default=0)               # precio por pax del buffet
    es_privado = db.Column(db.Boolean, default=False)            # grupo privado con cobro directo

    # Totales
    subtotal = db.Column(db.Float, default=0)
    descuento = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)

    # Pago (solo grupos privados — el resto va al cierre diario)
    tipo_pago = db.Column(db.String(30))
    estado_pago = db.Column(db.String(20), default='pendiente')
    tipo_comprobante = db.Column(db.String(30))
    serie_comprobante = db.Column(db.String(20))
    numero_comprobante = db.Column(db.String(30))

    observaciones = db.Column(db.Text)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    creado_en = db.Column(db.DateTime, default=now_peru)

    empresa = db.relationship('EmpresaTuristica')
    usuario = db.relationship('Usuario')
    items = db.relationship('ItemVenta', backref='venta', lazy=True, cascade='all, delete-orphan')


class CierreCaja(db.Model):
    """Cierre de caja al final del día — resumen de medios de pago"""
    __tablename__ = 'cierres_caja'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, unique=True)
    efectivo = db.Column(db.Float, default=0)
    tarjeta = db.Column(db.Float, default=0)
    yape = db.Column(db.Float, default=0)
    transferencia = db.Column(db.Float, default=0)
    total_cobrado = db.Column(db.Float, default=0)
    observaciones = db.Column(db.Text)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    creado_en = db.Column(db.DateTime, default=now_peru)
    usuario = db.relationship('Usuario')


class ItemVenta(db.Model):
    __tablename__ = 'items_venta'
    id = db.Column(db.Integer, primary_key=True)
    venta_id = db.Column(db.Integer, db.ForeignKey('ventas_diarias.id'), nullable=False)
    producto_carta_id = db.Column(db.Integer, db.ForeignKey('productos_carta.id'), nullable=True)
    variante_id = db.Column(db.Integer, db.ForeignKey('variantes_carta.id'), nullable=True)
    descripcion = db.Column(db.String(200), nullable=False)
    cantidad = db.Column(db.Integer, default=1)
    precio_unitario = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)

    producto_carta = db.relationship('ProductoCarta')
    variante = db.relationship('VarianteCarta')

# ═══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════
#  MÓDULO EMPLEADOS
# ══════════════════════════════════════════════
class Empleado(db.Model):
    __tablename__ = 'empleados'
    id               = db.Column(db.Integer, primary_key=True)
    nombres          = db.Column(db.String(100), nullable=False)
    apellidos        = db.Column(db.String(100), nullable=False)
    dni              = db.Column(db.String(20), unique=True, nullable=True)
    telefono         = db.Column(db.String(20))
    direccion        = db.Column(db.String(255))
    fecha_nacimiento = db.Column(db.Date)
    tipo_sangre      = db.Column(db.String(5))
    cargo            = db.Column(db.String(100))
    fecha_ingreso    = db.Column(db.Date)
    tipo_contrato    = db.Column(db.String(20), default='fijo')  # fijo | por_dia
    sueldo_base      = db.Column(db.Float, default=0)
    activo           = db.Column(db.Boolean, default=True)
    usuario_id       = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    usuario          = db.relationship('Usuario', foreign_keys=[usuario_id])
    asistencias      = db.relationship('Asistencia', backref='empleado', lazy=True, cascade='all, delete-orphan')
    funciones_dia    = db.relationship('FuncionDiaria', backref='empleado', lazy=True, cascade='all, delete-orphan')

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}"

    @property
    def cumpleanos_hoy(self):
        from datetime import date
        if self.fecha_nacimiento:
            hoy = date.today()
            return (self.fecha_nacimiento.month == hoy.month and
                    self.fecha_nacimiento.day == hoy.day)
        return False

    @property
    def edad(self):
        from datetime import date
        if self.fecha_nacimiento:
            hoy = date.today()
            return hoy.year - self.fecha_nacimiento.year - (
                (hoy.month, hoy.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day))
        return None

    @property
    def dias_para_cumpleanos(self):
        from datetime import date
        if not self.fecha_nacimiento:
            return None
        hoy = date.today()
        try:
            proximo = self.fecha_nacimiento.replace(year=hoy.year)
        except ValueError:
            proximo = self.fecha_nacimiento.replace(year=hoy.year, day=28)
        if proximo < hoy:
            try:
                proximo = self.fecha_nacimiento.replace(year=hoy.year + 1)
            except ValueError:
                proximo = self.fecha_nacimiento.replace(year=hoy.year + 1, day=28)
        return (proximo - hoy).days


class Asistencia(db.Model):
    __tablename__ = 'asistencias'
    id             = db.Column(db.Integer, primary_key=True)
    empleado_id    = db.Column(db.Integer, db.ForeignKey('empleados.id'), nullable=False)
    fecha          = db.Column(db.Date, nullable=False)
    estado         = db.Column(db.String(20), default='presente')  # presente|falta|tardanza|libre|feriado
    hora_entrada   = db.Column(db.String(10))
    hora_salida    = db.Column(db.String(10))
    horas_extra    = db.Column(db.Float, default=0)
    descuento      = db.Column(db.Float, default=0)
    observacion    = db.Column(db.String(255))
    registrado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    creado_en      = db.Column(db.DateTime, default=now_peru)
    __table_args__ = (db.UniqueConstraint('empleado_id', 'fecha', name='uq_asistencia_dia'),)


class FuncionDiaria(db.Model):
    __tablename__ = 'funciones_diarias'
    id             = db.Column(db.Integer, primary_key=True)
    empleado_id    = db.Column(db.Integer, db.ForeignKey('empleados.id'), nullable=False)
    fecha          = db.Column(db.Date, nullable=False)
    funcion        = db.Column(db.String(200), nullable=False)
    area           = db.Column(db.String(50))
    completado     = db.Column(db.Boolean, default=False)
    observacion    = db.Column(db.String(255))
    registrado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    creado_en      = db.Column(db.DateTime, default=now_peru)


# ══════════════════════════════════════════════
#  NOTIFICACIONES / REPORTES DE IRREGULARIDADES
# ══════════════════════════════════════════════
class Notificacion(db.Model):
    __tablename__ = 'notificaciones'
    id            = db.Column(db.Integer, primary_key=True)
    tipo          = db.Column(db.String(30), default='info')   # info | warning | error | irregularidad
    titulo        = db.Column(db.String(200), nullable=False)
    mensaje       = db.Column(db.Text)
    referencia_id = db.Column(db.Integer)           # ID del pedido/lista relacionado
    referencia_tipo = db.Column(db.String(30))      # 'pedido', 'compra', etc.
    destinatario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    destinatario  = db.relationship('Usuario', foreign_keys=[destinatario_id])
    leido         = db.Column(db.Boolean, default=False)
    creado_en     = db.Column(db.DateTime, default=now_peru)
    creado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    creado_por    = db.relationship('Usuario', foreign_keys=[creado_por_id])
