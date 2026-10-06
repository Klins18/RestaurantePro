from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, Producto, Categoria, KardexAlmacen, Bien, CategoriaBien, KardexBienes
from routes.helpers import agrupar_por_categoria
from datetime import datetime, date, timedelta
import pytz

kardex_bp = Blueprint('kardex', __name__, url_prefix='/kardex')
PERU_TZ = pytz.timezone('America/Lima')


def recalcular_kardex_almacen(producto_id):
    """Recalcula saldos del kardex de almacén en orden cronológico (precio promedio ponderado)"""
    from services.kardex import recalcular_producto
    recalcular_producto(producto_id)
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

    productos = Producto.query.filter_by(activo=True).outerjoin(Categoria).order_by(
        Categoria.nombre.is_(None), Categoria.nombre, Producto.nombre
    ).all()
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

    saldo_actual = None
    if producto_sel:
        saldo_actual = KardexAlmacen.query.filter_by(producto_id=producto_sel.id).order_by(
            KardexAlmacen.fecha.desc(), KardexAlmacen.id.desc()
        ).first()

    # Valor total inventario — subquery para el último registro de cada producto
    from sqlalchemy import func
    subq = db.session.query(
        KardexAlmacen.producto_id,
        func.max(KardexAlmacen.id).label('max_id')
    ).group_by(KardexAlmacen.producto_id).subquery()
    ultima_fila = db.session.query(func.coalesce(func.sum(KardexAlmacen.total_saldo), 0.0)).join(
        subq, KardexAlmacen.id == subq.c.max_id
    ).scalar()
    valor_total_inv = float(ultima_fila or 0)

    return render_template('kardex/almacen.html',
        productos_por_categoria=agrupar_por_categoria(productos), registros=registros,
        producto_sel=producto_sel,
        saldo_actual=saldo_actual,
        desde=fecha_desde, hasta=fecha_hasta,
        valor_total_inv=valor_total_inv)


# ──────────────────────────────────────
#  KARDEX DE BIENES FÍSICOS
# ──────────────────────────────────────
@kardex_bp.route('/bienes')
@login_required
@permiso_required('inventario')
def bienes():
    bien_id = request.args.get('bien_id', type=int)
    area = request.args.get('area', '')
    categoria_id = request.args.get('categoria', type=int)
    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', '')

    bienes_activos = Bien.query.filter_by(activo=True).join(CategoriaBien).order_by(
        Bien.area, CategoriaBien.nombre, Bien.nombre
    ).all()
    bien_sel = Bien.query.filter_by(id=bien_id).first() if bien_id else None

    q = KardexBienes.query.join(Bien)
    if bien_sel:
        q = q.filter(KardexBienes.bien_id == bien_sel.id)
    if area:
        q = q.filter(Bien.area == area)
    if categoria_id:
        q = q.filter(Bien.categoria_id == categoria_id)
    if fecha_desde:
        try:
            q = q.filter(KardexBienes.fecha >= datetime.strptime(fecha_desde, '%Y-%m-%d'))
        except ValueError:
            fecha_desde = ''
    if fecha_hasta:
        try:
            limite = datetime.strptime(fecha_hasta, '%Y-%m-%d') + timedelta(days=1)
            q = q.filter(KardexBienes.fecha < limite)
        except ValueError:
            fecha_hasta = ''

    registros = q.order_by(KardexBienes.fecha.desc(), KardexBienes.id.desc()).limit(500).all()
    cantidad_bienes = len(bienes_activos)
    total_unidades = sum(b.total or 0 for b in bienes_activos)
    bienes_sin_costo = sum(1 for b in bienes_activos if b.costo_unitario is None)
    valor_registrado = sum(
        (b.total or 0) * b.costo_unitario
        for b in bienes_activos if b.costo_unitario is not None
    )
    grupos_bienes = {}
    for bien in bienes_activos:
        etiqueta = f'{bien.area or "Sin área"} · {bien.categoria.nombre if bien.categoria else "Sin categoría"}'
        grupos_bienes.setdefault(etiqueta, []).append(bien)

    return render_template(
        'kardex/bienes.html',
        bienes_por_categoria=list(grupos_bienes.items()),
        registros=registros,
        bien_sel=bien_sel,
        area=area,
        categoria_id=categoria_id,
        desde=fecha_desde,
        hasta=fecha_hasta,
        cantidad_bienes=cantidad_bienes,
        total_unidades=total_unidades,
        bienes_sin_costo=bienes_sin_costo,
        valor_registrado=valor_registrado,
    )


@kardex_bp.route('/comedor')
@login_required
@permiso_required('inventario')
def comedor_legacy():
    return redirect(url_for('kardex.bienes'))
