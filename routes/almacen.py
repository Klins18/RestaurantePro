from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, Producto, Categoria, MovimientoAlmacen, Proveedor, registrar_auditoria
from datetime import datetime, date, timedelta
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
    solo_bajos = request.args.get('bajos', '')

    q = Producto.query.filter_by(activo=True)
    if categoria_id:
        q = q.filter_by(categoria_id=int(categoria_id))
    if q_filtro:
        q = q.filter(Producto.nombre.ilike(f'%{q_filtro}%'))
    if solo_bajos:
        q = q.filter(Producto.stock_actual <= Producto.stock_minimo,
                     Producto.stock_minimo > 0)

    productos = q.order_by(Producto.nombre).all()
    categorias = Categoria.query.filter_by(activo=True).order_by(Categoria.nombre).all()
    alertas = sum(1 for p in Producto.query.filter_by(activo=True).all()
                  if p.stock_actual <= p.stock_minimo and p.stock_minimo > 0)

    return render_template('almacen/index.html',
                           productos=productos, categorias=categorias,
                           cat_filtro=categoria_id, q_filtro=q_filtro,
                           solo_bajos=solo_bajos, alertas=alertas)

# ──────────────────────────────────────
#  ALERTAS DE STOCK
# ──────────────────────────────────────
@almacen_bp.route('/alertas')
@login_required
@permiso_required('inventario')
def alertas():
    """Productos bajo stock mínimo con detalle de últimos movimientos."""
    productos_bajos = Producto.query.filter(
        Producto.activo == True,
        Producto.stock_actual <= Producto.stock_minimo,
        Producto.stock_minimo > 0
    ).order_by(
        (Producto.stock_actual / Producto.stock_minimo)
    ).all()

    # Para cada producto, último ingreso
    detalle = []
    for p in productos_bajos:
        ultimo_ing = MovimientoAlmacen.query.filter_by(
            producto_id=p.id, tipo='ingreso'
        ).order_by(MovimientoAlmacen.fecha_hora.desc()).first()
        detalle.append({'producto': p, 'ultimo_ingreso': ultimo_ing})

    return render_template('almacen/alertas.html', detalle=detalle)

# ──────────────────────────────────────
#  REGISTRAR INGRESO
# ──────────────────────────────────────
@almacen_bp.route('/ingreso', methods=['GET', 'POST'])
@login_required
@permiso_required('inventario')
def ingreso():
    if request.method == 'POST':
        producto_id = request.form.get('producto_id')
        try:
            cantidad = float(request.form.get('cantidad', '0'))
        except:
            flash('Cantidad inválida', 'error')
            return redirect(request.url)

        producto = Producto.query.get_or_404(producto_id)
        producto.stock_actual += cantidad

        db.session.add(MovimientoAlmacen(
            tipo='ingreso',
            producto_id=producto.id,
            cantidad=cantidad,
            unidad_medida=producto.unidad_medida,
            motivo=request.form.get('motivo', ''),
            referencia=request.form.get('referencia', ''),
            proveedor_id=request.form.get('proveedor_id') or None,
            usuario_id=current_user.id,
            fecha_hora=now_peru(),
            observaciones=request.form.get('observaciones', '')
        ))
        registrar_auditoria(current_user.id, 'INGRESO_ALMACEN', 'movimientos_almacen',
                            None, f'{producto.nombre} | +{cantidad}', ip=request.remote_addr)
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
        try:
            cantidad = float(request.form.get('cantidad', '0'))
        except:
            flash('Cantidad inválida', 'error')
            return redirect(request.url)

        producto = Producto.query.get_or_404(producto_id)
        if producto.stock_actual < cantidad:
            flash(f'Stock insuficiente. Disponible: {producto.stock_actual} {producto.unidad_medida}', 'error')
            return redirect(request.url)

        producto.stock_actual -= cantidad
        db.session.add(MovimientoAlmacen(
            tipo='egreso',
            producto_id=producto.id,
            cantidad=cantidad,
            unidad_medida=producto.unidad_medida,
            motivo=request.form.get('motivo', ''),
            referencia=request.form.get('referencia', ''),
            usuario_id=current_user.id,
            fecha_hora=now_peru(),
            observaciones=request.form.get('observaciones', '')
        ))
        registrar_auditoria(current_user.id, 'EGRESO_ALMACEN', 'movimientos_almacen',
                            None, f'{producto.nombre} | -{cantidad}', ip=request.remote_addr)
        db.session.commit()
        flash(f'Salida de {cantidad} {producto.unidad_medida} de "{producto.nombre}" registrada.', 'success')
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
    hoy = date.today()
    tipo        = request.args.get('tipo', '')
    producto_id = request.args.get('producto', '')
    desde_str   = request.args.get('desde', hoy.strftime('%Y-%m-%d'))
    hasta_str   = request.args.get('hasta',  hoy.strftime('%Y-%m-%d'))

    q = MovimientoAlmacen.query.order_by(MovimientoAlmacen.fecha_hora.desc())
    if tipo:
        q = q.filter_by(tipo=tipo)
    if producto_id:
        q = q.filter_by(producto_id=int(producto_id))
    try:
        q = q.filter(MovimientoAlmacen.fecha_hora >=
                     datetime.strptime(desde_str, '%Y-%m-%d'))
    except: pass
    try:
        q = q.filter(MovimientoAlmacen.fecha_hora <
                     datetime.strptime(hasta_str, '%Y-%m-%d') + timedelta(days=1))
    except: pass

    movs = q.limit(500).all()

    # Totales del período
    total_ingresos = sum(m.cantidad for m in movs if m.tipo == 'ingreso')
    total_egresos  = sum(m.cantidad for m in movs if m.tipo == 'egreso')

    # Resumen por producto (para la vista de salidas)
    resumen = {}
    for m in movs:
        pid = m.producto_id
        if pid not in resumen:
            resumen[pid] = {
                'nombre': m.producto.nombre,
                'unidad': m.producto.unidad_medida,
                'stock':  m.producto.stock_actual,
                'ingresos': 0, 'egresos': 0, 'movimientos': 0
            }
        resumen[pid]['movimientos'] += 1
        if m.tipo == 'ingreso':
            resumen[pid]['ingresos'] += m.cantidad
        else:
            resumen[pid]['egresos'] += m.cantidad

    resumen_lista = sorted(resumen.values(), key=lambda x: x['egresos'], reverse=True)

    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    return render_template('almacen/movimientos.html',
                           movimientos=movs,
                           total_ingresos=total_ingresos,
                           total_egresos=total_egresos,
                           resumen=resumen_lista,
                           productos=productos,
                           tipo_filtro=tipo,
                           prod_filtro=producto_id,
                           desde=desde_str, hasta=hasta_str)
