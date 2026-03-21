from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, Producto, ProductoCarta, KardexAlmacen, KardexComedor
from datetime import datetime, date
import pytz

kardex_bp = Blueprint('kardex', __name__, url_prefix='/kardex')
PERU_TZ = pytz.timezone('America/Lima')


def recalcular_kardex_almacen(producto_id):
    """Recalcula saldos del kardex de almacén en orden cronológico (precio promedio ponderado)"""
    registros = KardexAlmacen.query.filter_by(producto_id=producto_id)\
        .order_by(KardexAlmacen.fecha, KardexAlmacen.id).all()
    saldo_cant = 0
    saldo_total = 0
    for r in registros:
        if r.tipo == 'ingreso':
            saldo_cant += r.cant_entrada
            saldo_total += r.total_entrada
            precio_prom = saldo_total / saldo_cant if saldo_cant > 0 else 0
            r.precio_salida = precio_prom
            r.precio_saldo = precio_prom
        elif r.tipo == 'egreso':
            precio_prom = saldo_total / saldo_cant if saldo_cant > 0 else 0
            r.precio_salida = precio_prom
            r.total_salida = r.cant_salida * precio_prom
            saldo_cant -= r.cant_salida
            saldo_total -= r.total_salida
            r.precio_saldo = saldo_total / saldo_cant if saldo_cant > 0 else 0
        r.cant_saldo = round(saldo_cant, 4)
        r.total_saldo = round(saldo_total, 2)
    db.session.commit()


# ──────────────────────────────────────
#  KARDEX ALMACÉN
# ──────────────────────────────────────
@kardex_bp.route('/almacen')
@login_required
@permiso_required('inventario')
def almacen():
    producto_id = request.args.get('producto_id', type=int)
    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', '')

    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    registros = []
    producto_sel = None

    if producto_id:
        producto_sel = Producto.query.get(producto_id)
        q = KardexAlmacen.query.filter_by(producto_id=producto_id)
        if fecha_desde:
            try:
                q = q.filter(KardexAlmacen.fecha >= datetime.strptime(fecha_desde, '%Y-%m-%d'))
            except: pass
        if fecha_hasta:
            try:
                from datetime import timedelta
                d = datetime.strptime(fecha_hasta, '%Y-%m-%d') + timedelta(days=1)
                q = q.filter(KardexAlmacen.fecha < d)
            except: pass
        registros = q.order_by(KardexAlmacen.fecha, KardexAlmacen.id).all()

    # Valor total inventario — subquery para el último registro de cada producto
    from sqlalchemy import func, text as sa_text
    subq = db.session.query(
        KardexAlmacen.producto_id,
        func.max(KardexAlmacen.id).label('max_id')
    ).group_by(KardexAlmacen.producto_id).subquery()
    ultima_fila = db.session.query(func.coalesce(func.sum(KardexAlmacen.total_saldo), 0.0)).join(
        subq, KardexAlmacen.id == subq.c.max_id
    ).scalar()
    valor_total_inv = float(ultima_fila or 0)

    return render_template('kardex/almacen.html',
        productos=productos, registros=registros,
        producto_sel=producto_sel,
        desde=fecha_desde, hasta=fecha_hasta,
        valor_total_inv=valor_total_inv)


# ──────────────────────────────────────
#  KARDEX COMEDOR
# ──────────────────────────────────────
@kardex_bp.route('/comedor')
@login_required
@permiso_required('inventario')
def comedor():
    producto_id = request.args.get('producto_id', type=int)
    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', '')

    productos = ProductoCarta.query.filter_by(activo=True).order_by(ProductoCarta.nombre).all()
    registros = []
    producto_sel = None

    if producto_id:
        producto_sel = ProductoCarta.query.get(producto_id)
        q = KardexComedor.query.filter_by(producto_carta_id=producto_id)
        if fecha_desde:
            try:
                q = q.filter(KardexComedor.fecha >= datetime.strptime(fecha_desde, '%Y-%m-%d'))
            except: pass
        if fecha_hasta:
            try:
                from datetime import timedelta
                d = datetime.strptime(fecha_hasta, '%Y-%m-%d') + timedelta(days=1)
                q = q.filter(KardexComedor.fecha < d)
            except: pass
        registros = q.order_by(KardexComedor.fecha, KardexComedor.id).all()

    # Total ingresos del mes actual
    from datetime import date
    from models import KardexComedor as KC
    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    registros_mes = KC.query.filter(
        KC.fecha >= datetime.combine(inicio_mes, datetime.min.time())
    ).all()
    total_ingresos_mes = sum(r.total_entrada or 0 for r in registros_mes if r.tipo == 'ingreso')

    return render_template('kardex/comedor.html',
        productos=productos, registros=registros,
        producto_sel=producto_sel,
        desde=fecha_desde, hasta=fecha_hasta,
        total_ingresos_mes=total_ingresos_mes)
