from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
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
def almacen():
    from datetime import timedelta
    hoy = date.today()
    producto_id = request.args.get('producto_id', type=int)
    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', '')

    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    registros = []
    producto_sel = None

    # ── Resumen general: estado actual de TODO el inventario ──
    resumen_stock = []
    valor_total_inv = 0
    alertas_stock = []
    for p in productos:
        ultimo = KardexAlmacen.query.filter_by(producto_id=p.id)            .order_by(KardexAlmacen.id.desc()).first()
        stock = ultimo.cant_saldo if ultimo else p.stock_actual or 0
        precio_prom = ultimo.precio_saldo if ultimo else 0
        valor = round(stock * precio_prom, 2)
        valor_total_inv += valor
        # Movimientos últimos 30 días
        desde_30 = datetime.combine(hoy - timedelta(days=30), datetime.min.time())
        movs_mes = KardexAlmacen.query.filter(
            KardexAlmacen.producto_id == p.id,
            KardexAlmacen.fecha >= desde_30
        ).count()
        alerta = None
        if stock <= 0:
            alerta = 'sin_stock'
        elif p.stock_minimo and stock <= p.stock_minimo:
            alerta = 'bajo'
        if alerta:
            alertas_stock.append({'nombre': p.nombre, 'stock': stock,
                                   'unidad': p.unidad_medida, 'tipo': alerta,
                                   'id': p.id})
        resumen_stock.append({
            'id': p.id, 'nombre': p.nombre, 'unidad': p.unidad_medida,
            'stock': round(stock, 3), 'precio_prom': precio_prom,
            'valor': valor, 'movs_mes': movs_mes,
            'stock_minimo': p.stock_minimo or 0, 'alerta': alerta,
            'categoria': p.categoria.nombre if p.categoria_id and hasattr(p, 'categoria') and p.categoria else '—'
        })

    # Movimientos recientes (últimos 10 días, todos los productos)
    desde_reciente = datetime.combine(hoy - timedelta(days=10), datetime.min.time())
    movimientos_recientes = KardexAlmacen.query        .filter(KardexAlmacen.fecha >= desde_reciente)        .order_by(KardexAlmacen.fecha.desc(), KardexAlmacen.id.desc())        .limit(50).all()

    if producto_id:
        producto_sel = Producto.query.get(producto_id)
        q = KardexAlmacen.query.filter_by(producto_id=producto_id)
        if fecha_desde:
            try:
                q = q.filter(KardexAlmacen.fecha >= datetime.strptime(fecha_desde, '%Y-%m-%d'))
            except: pass
        if fecha_hasta:
            try:
                d = datetime.strptime(fecha_hasta, '%Y-%m-%d') + timedelta(days=1)
                q = q.filter(KardexAlmacen.fecha < d)
            except: pass
        registros = q.order_by(KardexAlmacen.fecha, KardexAlmacen.id).all()

    return render_template('kardex/almacen.html',
        productos=productos, registros=registros,
        producto_sel=producto_sel,
        desde=fecha_desde, hasta=fecha_hasta,
        resumen_stock=resumen_stock,
        valor_total_inv=round(valor_total_inv, 2),
        alertas_stock=alertas_stock,
        movimientos_recientes=movimientos_recientes,
        hoy=hoy)


# ──────────────────────────────────────
#  KARDEX COMEDOR
# ──────────────────────────────────────
@kardex_bp.route('/comedor')
@login_required
def comedor():
    from datetime import timedelta
    hoy = date.today()
    producto_id = request.args.get('producto_id', type=int)
    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', hoy.strftime('%Y-%m-%d'))
    if not fecha_desde:
        fecha_desde = (hoy.replace(day=1)).strftime('%Y-%m-%d')  # inicio del mes

    productos = ProductoCarta.query.filter_by(activo=True).order_by(ProductoCarta.nombre).all()
    registros = []
    producto_sel = None

    # ── Resumen general de ventas del mes por producto de carta ──
    desde_dt = datetime.strptime(fecha_desde, '%Y-%m-%d')
    hasta_dt = datetime.strptime(fecha_hasta, '%Y-%m-%d') + timedelta(days=1)

    resumen_carta = []
    total_ingresos_mes = 0
    for p in productos:
        movs = KardexComedor.query.filter(
            KardexComedor.producto_carta_id == p.id,
            KardexComedor.fecha >= desde_dt,
            KardexComedor.fecha < hasta_dt
        ).all()
        ventas = [m for m in movs if m.tipo == 'venta']
        und_vendidas = sum(v.cant_salida or 0 for v in ventas)
        ingreso_total = und_vendidas * p.precio
        total_ingresos_mes += ingreso_total
        ultimo = KardexComedor.query.filter_by(producto_carta_id=p.id)            .order_by(KardexComedor.id.desc()).first()
        stock_actual = ultimo.cant_saldo if ultimo else 0
        resumen_carta.append({
            'id': p.id, 'nombre': p.nombre, 'precio': p.precio,
            'und_vendidas': int(und_vendidas),
            'ingreso_total': round(ingreso_total, 2),
            'stock_actual': round(stock_actual, 1),
            'movimientos': len(movs),
            'categoria': p.categoria_carta.nombre if p.categoria_carta else '—'
        })
    resumen_carta.sort(key=lambda x: x['und_vendidas'], reverse=True)

    # Ventas recientes (últimos 7 días)
    desde_7 = datetime.combine(hoy - timedelta(days=7), datetime.min.time())
    ventas_recientes = KardexComedor.query        .filter(KardexComedor.fecha >= desde_7, KardexComedor.tipo == 'venta')        .order_by(KardexComedor.fecha.desc(), KardexComedor.id.desc())        .limit(40).all()

    if producto_id:
        producto_sel = ProductoCarta.query.get(producto_id)
        q = KardexComedor.query.filter_by(producto_carta_id=producto_id)
        try:
            q = q.filter(KardexComedor.fecha >= desde_dt)
            q = q.filter(KardexComedor.fecha < hasta_dt)
        except: pass
        registros = q.order_by(KardexComedor.fecha, KardexComedor.id).all()

    return render_template('kardex/comedor.html',
        productos=productos, registros=registros,
        producto_sel=producto_sel,
        desde=fecha_desde, hasta=fecha_hasta,
        resumen_carta=resumen_carta,
        total_ingresos_mes=round(total_ingresos_mes, 2),
        ventas_recientes=ventas_recientes,
        hoy=hoy)
