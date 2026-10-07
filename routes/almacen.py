from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, Producto, Categoria, MovimientoAlmacen, Proveedor, registrar_auditoria
from services.units import normalize_unit
from services.kardex import registrar_kardex
from routes.helpers import agrupar_por_categoria
from datetime import datetime, date, timedelta
import math
import pytz
from sqlalchemy import func

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
        cat_id = request.args.get('categoria', type=int)
        if cat_id:
            q = q.filter_by(categoria_id=cat_id)
    if q_filtro:
        q = q.filter(Producto.nombre.ilike(f'%{q_filtro}%'))
    if solo_bajos:
        q = q.filter(Producto.stock_actual <= Producto.stock_minimo,
                     Producto.stock_minimo > 0)

    productos = q.outerjoin(Categoria).order_by(
        Categoria.nombre.is_(None), Categoria.nombre, Producto.nombre
    ).all()
    categorias = Categoria.query.filter_by(activo=True).order_by(Categoria.nombre).all()
    alertas = Producto.query.filter(
        Producto.activo.is_(True),
        Producto.stock_actual <= Producto.stock_minimo,
        Producto.stock_minimo > 0,
    ).count()

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

    ultimo_ingreso = db.session.query(
        MovimientoAlmacen.producto_id.label('producto_id'),
        func.max(MovimientoAlmacen.id).label('mov_id'),
    ).filter(MovimientoAlmacen.tipo == 'ingreso').group_by(
        MovimientoAlmacen.producto_id
    ).subquery()
    ingresos = dict(db.session.query(
        MovimientoAlmacen.producto_id, MovimientoAlmacen
    ).join(ultimo_ingreso, MovimientoAlmacen.id == ultimo_ingreso.c.mov_id).all())
    detalle = [{'producto': p, 'ultimo_ingreso': ingresos.get(p.id)} for p in productos_bajos]

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
        if cantidad <= 0 or not math.isfinite(cantidad):
            flash('La cantidad debe ser mayor que cero.', 'error')
            return redirect(request.url)

        costo_raw = request.form.get('costo_unitario', '').strip()
        try:
            costo_unitario = float(costo_raw) if costo_raw else None
            if costo_unitario is not None and (costo_unitario < 0 or not math.isfinite(costo_unitario)):
                raise ValueError
        except ValueError:
            flash('El costo unitario debe ser un monto igual o mayor que cero.', 'error')
            return redirect(request.url)
        fecha_mov = now_peru()
        fecha_raw = request.form.get('fecha', '').strip()
        if fecha_raw:
            try:
                fecha_elegida = datetime.strptime(fecha_raw, '%Y-%m-%d').date()
                fecha_mov = datetime.combine(fecha_elegida, fecha_mov.time())
            except ValueError:
                flash('La fecha ingresada no es válida.', 'error')
                return redirect(request.url)

        producto = Producto.query.get_or_404(producto_id)
        if costo_unitario is not None and costo_unitario > 0:
            producto.costo_unitario = costo_unitario
        producto.stock_actual += cantidad

        db.session.add(MovimientoAlmacen(
            tipo='ingreso',
            producto_id=producto.id,
            cantidad=cantidad,
            unidad_medida=normalize_unit(producto.unidad_medida),
            motivo=request.form.get('motivo', ''),
            referencia=request.form.get('referencia', ''),
            proveedor_id=request.form.get('proveedor_id') or None,
            usuario_id=current_user.id,
            fecha_hora=fecha_mov,
            observaciones=request.form.get('observaciones', '')
        ))
        registrar_kardex(
            producto.id, 'ingreso', cantidad, current_user.id,
            concepto=request.form.get('motivo', '').strip() or 'Ingreso manual',
            referencia=request.form.get('referencia', '').strip(),
            fecha=fecha_mov, precio_unitario=costo_unitario,
        )
        registrar_auditoria(current_user.id, 'INGRESO_ALMACEN', 'movimientos_almacen',
                            None, f'{producto.nombre} | +{cantidad}', ip=request.remote_addr)
        db.session.commit()
        flash(f'Ingreso de {cantidad} {producto.unidad_medida} de "{producto.nombre}" registrado.', 'success')
        return redirect(url_for('almacen.movimientos'))

    productos = Producto.query.filter_by(activo=True).outerjoin(Categoria).order_by(
        Categoria.nombre.is_(None), Categoria.nombre, Producto.nombre
    ).all()
    proveedores = Proveedor.query.filter_by(activo=True).order_by(Proveedor.nombre).all()
    return render_template(
        'almacen/ingreso.html',
        productos_por_categoria=agrupar_por_categoria(productos),
        proveedores=proveedores,
        hoy=now_peru().date(),
    )

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
        if cantidad <= 0 or not math.isfinite(cantidad):
            flash('La cantidad debe ser mayor que cero.', 'error')
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
            unidad_medida=normalize_unit(producto.unidad_medida),
            motivo=request.form.get('motivo', ''),
            referencia=request.form.get('referencia', ''),
            usuario_id=current_user.id,
            fecha_hora=now_peru(),
            observaciones=request.form.get('observaciones', '')
        ))
        registrar_kardex(
            producto.id, 'egreso', cantidad, current_user.id,
            concepto=request.form.get('motivo', '').strip() or 'Egreso manual',
            referencia=request.form.get('referencia', '').strip(),
            fecha=now_peru(),
        )
        registrar_auditoria(current_user.id, 'EGRESO_ALMACEN', 'movimientos_almacen',
                            None, f'{producto.nombre} | -{cantidad}', ip=request.remote_addr)
        db.session.commit()
        flash(f'Salida de {cantidad} {producto.unidad_medida} de "{producto.nombre}" registrada.', 'success')
        return redirect(url_for('almacen.movimientos'))

    productos = Producto.query.filter_by(activo=True).outerjoin(Categoria).order_by(
        Categoria.nombre.is_(None), Categoria.nombre, Producto.nombre
    ).all()
    return render_template('almacen/egreso.html', productos_por_categoria=agrupar_por_categoria(productos))

# ──────────────────────────────────────
#  HISTORIAL DE MOVIMIENTOS
# ──────────────────────────────────────
@almacen_bp.route('/movimientos')
@login_required
@permiso_required('inventario')
def movimientos():
    hoy = now_peru().date()
    tipo        = request.args.get('tipo', '')
    producto_id = request.args.get('producto', type=int)
    desde_str   = request.args.get('desde', hoy.strftime('%Y-%m-%d'))
    hasta_str   = request.args.get('hasta',  hoy.strftime('%Y-%m-%d'))

    q = MovimientoAlmacen.query.order_by(MovimientoAlmacen.fecha_hora.desc())
    if tipo:
        q = q.filter_by(tipo=tipo)
    if producto_id:
        q = q.filter_by(producto_id=producto_id)
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

    productos = Producto.query.filter_by(activo=True).outerjoin(Categoria).order_by(
        Categoria.nombre.is_(None), Categoria.nombre, Producto.nombre
    ).all()
    return render_template('almacen/movimientos.html',
                           movimientos=movs,
                           total_ingresos=total_ingresos,
                           total_egresos=total_egresos,
                           resumen=resumen_lista,
                           productos_por_categoria=agrupar_por_categoria(productos),
                           tipo_filtro=tipo,
                           prod_filtro=producto_id,
                           desde=desde_str, hasta=hasta_str)
