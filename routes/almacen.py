from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, Producto, Categoria, MovimientoAlmacen, Proveedor, registrar_auditoria
from datetime import datetime
import pytz

almacen_bp = Blueprint('almacen', __name__, url_prefix='/almacen')
PERU_TZ = pytz.timezone('America/Lima')

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

# ──────────────────────────────────────
#  INVENTARIO / STOCK
# ──────────────────────────────────────
@almacen_bp.route('/')
@login_required
@permiso_required('inventario')
def index():
    categoria_id = request.args.get('categoria', '')
    q_filtro = request.args.get('q', '').strip()
    q = Producto.query.filter_by(activo=True)
    if categoria_id:
        q = q.filter_by(categoria_id=int(categoria_id))
    if q_filtro:
        q = q.filter(Producto.nombre.ilike(f'%{q_filtro}%'))
    productos = q.order_by(Producto.nombre).all()
    categorias = Categoria.query.filter_by(activo=True).order_by(Categoria.nombre).all()
    alertas = sum(1 for p in productos if p.stock_actual <= p.stock_minimo)
    return render_template('almacen/index.html', productos=productos,
                           categorias=categorias, cat_filtro=categoria_id,
                           q_filtro=q_filtro, alertas=alertas)

# ──────────────────────────────────────
#  REGISTRAR INGRESO
# ──────────────────────────────────────
@almacen_bp.route('/ingreso', methods=['GET', 'POST'])
@login_required
@permiso_required('inventario')
def ingreso():
    if request.method == 'POST':
        producto_id = request.form.get('producto_id')
        cantidad_str = request.form.get('cantidad', '0')
        motivo = request.form.get('motivo', '')
        referencia = request.form.get('referencia', '')
        proveedor_id = request.form.get('proveedor_id') or None
        observaciones = request.form.get('observaciones', '')

        try:
            cantidad = float(cantidad_str)
        except:
            flash('Cantidad inválida', 'error')
            return redirect(request.url)

        producto = Producto.query.get_or_404(producto_id)
        producto.stock_actual += cantidad

        mov = MovimientoAlmacen(
            tipo='ingreso',
            producto_id=producto.id,
            cantidad=cantidad,
            unidad_medida=producto.unidad_medida,
            motivo=motivo,
            referencia=referencia,
            proveedor_id=proveedor_id,
            usuario_id=current_user.id,
            fecha_hora=now_peru(),
            observaciones=observaciones
        )
        db.session.add(mov)
        registrar_auditoria(current_user.id, 'INGRESO_ALMACEN',
                            'movimientos_almacen', None,
                            f'Producto: {producto.nombre} | Cant: {cantidad}',
                            ip=request.remote_addr)
        db.session.commit()
        flash(f'Ingreso de {cantidad} {producto.unidad_medida} de "{producto.nombre}" registrado.', 'success')
        return redirect(url_for('almacen.movimientos'))

    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    proveedores = Proveedor.query.filter_by(activo=True).order_by(Proveedor.nombre).all()
    return render_template('almacen/ingreso.html', productos=productos, proveedores=proveedores)

# ──────────────────────────────────────
#  REGISTRAR EGRESO / SALIDA
# ──────────────────────────────────────
@almacen_bp.route('/egreso', methods=['GET', 'POST'])
@login_required
@permiso_required('inventario')
def egreso():
    if request.method == 'POST':
        producto_id = request.form.get('producto_id')
        cantidad_str = request.form.get('cantidad', '0')
        motivo = request.form.get('motivo', '')
        referencia = request.form.get('referencia', '')
        observaciones = request.form.get('observaciones', '')

        try:
            cantidad = float(cantidad_str)
        except:
            flash('Cantidad inválida', 'error')
            return redirect(request.url)

        producto = Producto.query.get_or_404(producto_id)

        if producto.stock_actual < cantidad:
            flash(f'Stock insuficiente. Stock actual: {producto.stock_actual} {producto.unidad_medida}', 'error')
            return redirect(request.url)

        producto.stock_actual -= cantidad

        mov = MovimientoAlmacen(
            tipo='egreso',
            producto_id=producto.id,
            cantidad=cantidad,
            unidad_medida=producto.unidad_medida,
            motivo=motivo,
            referencia=referencia,
            usuario_id=current_user.id,
            fecha_hora=now_peru(),
            observaciones=observaciones
        )
        db.session.add(mov)
        registrar_auditoria(current_user.id, 'EGRESO_ALMACEN',
                            'movimientos_almacen', None,
                            f'Producto: {producto.nombre} | Cant: {cantidad}',
                            ip=request.remote_addr)
        db.session.commit()
        flash(f'Egreso de {cantidad} {producto.unidad_medida} de "{producto.nombre}" registrado.', 'success')
        return redirect(url_for('almacen.movimientos'))

    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    return render_template('almacen/egreso.html', productos=productos)

# ──────────────────────────────────────
#  HISTORIAL DE MOVIMIENTOS
# ──────────────────────────────────────
@almacen_bp.route('/movimientos')
@login_required
@permiso_required('inventario')
def movimientos():
    tipo = request.args.get('tipo', '')
    producto_id = request.args.get('producto', '')
    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', '')

    q = MovimientoAlmacen.query.order_by(MovimientoAlmacen.fecha_hora.desc())
    if tipo:
        q = q.filter_by(tipo=tipo)
    if producto_id:
        q = q.filter_by(producto_id=int(producto_id))
    if fecha_desde:
        try:
            d = datetime.strptime(fecha_desde, '%Y-%m-%d')
            q = q.filter(MovimientoAlmacen.fecha_hora >= d)
        except: pass
    if fecha_hasta:
        try:
            d = datetime.strptime(fecha_hasta, '%Y-%m-%d')
            from datetime import timedelta
            q = q.filter(MovimientoAlmacen.fecha_hora < d + timedelta(days=1))
        except: pass

    movimientos = q.limit(200).all()
    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    return render_template('almacen/movimientos.html', movimientos=movimientos,
                           productos=productos, tipo_filtro=tipo,
                           prod_filtro=producto_id,
                           desde=fecha_desde, hasta=fecha_hasta)
