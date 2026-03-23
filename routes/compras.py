import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, Compra, ItemCompra, Proveedor, Producto, KardexAlmacen, registrar_auditoria
from datetime import datetime, date
import pytz
from werkzeug.utils import secure_filename

compras_bp = Blueprint('compras', __name__, url_prefix='/compras')
PERU_TZ = pytz.timezone('America/Lima')
UPLOAD_FOLDER = 'static/uploads/comprobantes'
ALLOWED = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED

def guardar_archivo(file):
    if file and file.filename and allowed_file(file.filename):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_')
        filename = ts + secure_filename(file.filename)
        path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(path)
        return filename
    return None


# ──────────────────────────────────────
#  LISTAR COMPRAS
# ──────────────────────────────────────
@compras_bp.route('/')
@login_required
@permiso_required('compras')
def index():
    hoy = date.today()
    desde_str = request.args.get('desde', date(hoy.year, hoy.month, 1).strftime('%Y-%m-%d'))
    hasta_str = request.args.get('hasta', hoy.strftime('%Y-%m-%d'))
    tipo      = request.args.get('tipo', '')
    q_str     = request.args.get('q', '').strip()
    con_arch  = request.args.get('con_archivo', '')

    q = Compra.query.order_by(Compra.fecha.desc(), Compra.creado_en.desc())
    try: q = q.filter(Compra.fecha >= datetime.strptime(desde_str, '%Y-%m-%d').date())
    except: pass
    try: q = q.filter(Compra.fecha <= datetime.strptime(hasta_str, '%Y-%m-%d').date())
    except: pass
    if tipo:
        q = q.filter(Compra.tipo_comprobante == tipo)
    if q_str:
        q = q.filter(
            (Compra.proveedor_nombre.ilike(f'%{q_str}%')) |
            (Compra.serie_comprobante.ilike(f'%{q_str}%')) |
            (Compra.numero_comprobante.ilike(f'%{q_str}%'))
        )
    if con_arch == '1':
        q = q.filter(Compra.archivo_comprobante.isnot(None), Compra.archivo_comprobante != '')
    elif con_arch == '0':
        q = q.filter((Compra.archivo_comprobante == None) | (Compra.archivo_comprobante == ''))

    compras = q.all()
    total_periodo = sum(c.total for c in compras)

    return render_template('compras/index.html', compras=compras,
        total_periodo=total_periodo, desde=desde_str, hasta=hasta_str,
        tipo=tipo, q=q_str, con_archivo=con_arch)


# ──────────────────────────────────────
#  NUEVA COMPRA
# ──────────────────────────────────────
@compras_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
@permiso_required('compras')
def nueva():
    if request.method == 'POST':
        # Guardar archivo adjunto
        archivo = guardar_archivo(request.files.get('archivo_comprobante'))

        fecha_str = request.form.get('fecha', '')
        fecha_pago_str = request.form.get('fecha_pago', '')
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha = date.today()
        try:
            fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d').date() if fecha_pago_str else None
        except:
            fecha_pago = None

        total = float(request.form.get('total', 0) or 0)
        subtotal = float(request.form.get('subtotal', 0) or 0)
        igv = float(request.form.get('igv', 0) or 0)

        compra = Compra(
            fecha=fecha,
            proveedor_id=request.form.get('proveedor_id') or None,
            proveedor_nombre=request.form.get('proveedor_nombre', '').strip(),
            tipo_comprobante=request.form.get('tipo_comprobante', ''),
            serie_comprobante=request.form.get('serie_comprobante', '').strip().upper(),
            numero_comprobante=request.form.get('numero_comprobante', '').strip(),
            archivo_comprobante=archivo,
            tipo_pago=request.form.get('tipo_pago', ''),
            fecha_pago=fecha_pago,
            numero_operacion=request.form.get('numero_operacion', '').strip(),
            subtotal=subtotal,
            igv=igv,
            total=total,
            observaciones=request.form.get('observaciones', ''),
            estado='pagado' if fecha_pago else 'registrado',
            usuario_id=current_user.id,
            creado_en=now_peru()
        )
        db.session.add(compra)
        db.session.flush()

        # Items de la compra
        descripciones = request.form.getlist('item_desc[]')
        cantidades = request.form.getlist('item_cant[]')
        unidades = request.form.getlist('item_unidad[]')
        precios = request.form.getlist('item_precio[]')
        producto_ids = request.form.getlist('item_producto_id[]')

        for i, desc in enumerate(descripciones):
            desc = desc.strip()
            if not desc:
                continue
            try:
                cant = float(cantidades[i]) if cantidades[i] else 0
                precio = float(precios[i]) if precios[i] else 0
            except:
                cant, precio = 0, 0
            subtotal_item = round(cant * precio, 2)

            prod_id = producto_ids[i] if i < len(producto_ids) and producto_ids[i] else None

            item = ItemCompra(
                compra_id=compra.id,
                producto_id=prod_id or None,
                descripcion=desc,
                cantidad=cant,
                unidad=unidades[i] if i < len(unidades) else '',
                precio_unitario=precio,
                subtotal=subtotal_item
            )
            db.session.add(item)

            # Si está vinculado a un producto, actualizar stock y kardex
            if prod_id:
                prod = Producto.query.get(prod_id)
                if prod:
                    # Obtener último saldo del kardex
                    ultimo = KardexAlmacen.query.filter_by(producto_id=prod.id)\
                        .order_by(KardexAlmacen.id.desc()).first()
                    cant_saldo_prev = ultimo.cant_saldo if ultimo else 0
                    total_saldo_prev = ultimo.total_saldo if ultimo else 0

                    nueva_cant = cant_saldo_prev + cant
                    nuevo_total = total_saldo_prev + subtotal_item
                    precio_prom = nuevo_total / nueva_cant if nueva_cant > 0 else precio

                    k = KardexAlmacen(
                        producto_id=prod.id,
                        fecha=datetime.combine(fecha, datetime.min.time()),
                        tipo='ingreso',
                        concepto=f"Compra - {compra.tipo_comprobante or ''} {compra.serie_comprobante or ''}-{compra.numero_comprobante or ''}".strip(),
                        referencia=f"{compra.serie_comprobante}-{compra.numero_comprobante}" if compra.numero_comprobante else '',
                        cant_entrada=cant,
                        precio_entrada=precio,
                        total_entrada=subtotal_item,
                        cant_saldo=nueva_cant,
                        precio_saldo=round(precio_prom, 4),
                        total_saldo=round(nuevo_total, 2),
                        usuario_id=current_user.id,
                        compra_id=compra.id
                    )
                    db.session.add(k)
                    prod.stock_actual += cant

        registrar_auditoria(current_user.id, 'NUEVA_COMPRA', 'compras', compra.id,
            f'Total: S/.{total:.2f}', ip=request.remote_addr)
        db.session.commit()
        flash(f'Compra registrada exitosamente. Total: S/.{total:.2f}', 'success')
        return redirect(url_for('compras.ver', id=compra.id))

    proveedores = Proveedor.query.filter_by(activo=True).order_by(Proveedor.nombre).all()
    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    # Serializar productos a dict para el JS del template
    productos_json = [
        {'id': p.id, 'nombre': p.nombre, 'unidad': p.unidad_medida}
        for p in productos
    ]
    return render_template('compras/nueva.html',
        proveedores=proveedores, productos=productos,
        productos_json=productos_json, hoy=date.today())


# ──────────────────────────────────────
#  VER COMPRA
# ──────────────────────────────────────
@compras_bp.route('/<int:id>')
@login_required
@permiso_required('compras')
def ver(id):
    compra = Compra.query.get_or_404(id)
    return render_template('compras/ver.html', compra=compra)


# ──────────────────────────────────────
#  DESCARGAR COMPROBANTE
# ──────────────────────────────────────
@compras_bp.route('/archivo/<filename>')
@login_required
def archivo(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ──────────────────────────────────────
#  ANULAR COMPRA (solo admin)
# ──────────────────────────────────────
@compras_bp.route('/<int:id>/anular', methods=['POST'])
@login_required
@admin_required
def anular(id):
    if not current_user.es_admin():
        flash('Solo el administrador puede anular compras.', 'error')
        return redirect(url_for('compras.ver', id=id))
    compra = Compra.query.get_or_404(id)
    compra.estado = 'anulado'
    registrar_auditoria(current_user.id, 'ANULAR_COMPRA', 'compras', id, ip=request.remote_addr)
    db.session.commit()
    flash('Compra anulada.', 'success')
    return redirect(url_for('compras.index'))


# ──────────────────────────────────────
#  CONSOLIDADO DIARIO
# ──────────────────────────────────────
@compras_bp.route('/consolidado')
@login_required
@permiso_required('compras')
def consolidado():
    from models import ItemCompra
    from sqlalchemy import func
    hoy = date.today()

    # Rango — por defecto mes actual
    desde_str = request.args.get('desde', date(hoy.year, hoy.month, 1).strftime('%Y-%m-%d'))
    hasta_str = request.args.get('hasta', hoy.strftime('%Y-%m-%d'))
    try:
        desde = datetime.strptime(desde_str, '%Y-%m-%d').date()
        hasta = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except:
        desde = date(hoy.year, hoy.month, 1)
        hasta = hoy

    # Compras del período (no anuladas)
    compras = Compra.query.filter(
        Compra.fecha >= desde,
        Compra.fecha <= hasta,
        Compra.estado != 'anulado'
    ).order_by(Compra.fecha).all()

    # ── Agrupar por día ──
    por_dia = {}
    for c in compras:
        d = c.fecha
        if d not in por_dia:
            por_dia[d] = {'compras': [], 'total': 0, 'n_comprobantes': 0}
        por_dia[d]['compras'].append(c)
        por_dia[d]['total'] = round(por_dia[d]['total'] + c.total, 2)
        por_dia[d]['n_comprobantes'] += 1

    dias_ordenados = sorted(por_dia.keys(), reverse=True)

    # ── Totales del período ──
    total_periodo  = sum(c.total for c in compras)
    total_dias     = len(por_dia)
    promedio_diario = round(total_periodo / total_dias, 2) if total_dias else 0

    # ── Resumen por proveedor ──
    por_proveedor = {}
    for c in compras:
        key = c.proveedor_nombre or (c.proveedor.nombre if c.proveedor else 'Sin proveedor')
        if key not in por_proveedor:
            por_proveedor[key] = {'total': 0, 'n': 0}
        por_proveedor[key]['total'] = round(por_proveedor[key]['total'] + c.total, 2)
        por_proveedor[key]['n'] += 1
    por_proveedor = sorted(por_proveedor.items(), key=lambda x: x[1]['total'], reverse=True)

    # ── Serie para gráfico ──
    # Llenar días sin compras con 0
    from datetime import timedelta
    serie = {}
    d = desde
    while d <= hasta:
        serie[d.strftime('%d/%m')] = round(por_dia.get(d, {}).get('total', 0), 2)
        d += timedelta(days=1)

    return render_template('compras/consolidado.html',
        por_dia=por_dia, dias_ordenados=dias_ordenados,
        total_periodo=total_periodo, total_dias=total_dias,
        promedio_diario=promedio_diario,
        por_proveedor=por_proveedor,
        serie=serie,
        desde=desde_str, hasta=hasta_str, hoy=hoy)

# ──────────────────────────────────────
#  COSTEO COMPARATIVO ENTRE MESES
# ──────────────────────────────────────
@compras_bp.route('/costeo')
@login_required
@permiso_required('compras')
def costeo():
    from models import ItemCompra
    from sqlalchemy import func, extract
    from datetime import timedelta

    hoy = date.today()

    # Meses disponibles (últimos 12)
    meses_disponibles = []
    d = date(hoy.year, hoy.month, 1)
    for _ in range(12):
        meses_disponibles.append(d)
        # Mes anterior
        if d.month == 1:
            d = date(d.year - 1, 12, 1)
        else:
            d = date(d.year, d.month - 1, 1)
    meses_disponibles.reverse()

    # Meses seleccionados (por defecto últimos 3)
    sel_raw = request.args.getlist('mes')  # formato: YYYY-MM
    if sel_raw:
        meses_sel = []
        for m in sel_raw:
            try:
                y, mo = m.split('-')
                meses_sel.append(date(int(y), int(mo), 1))
            except: pass
        if not meses_sel:
            meses_sel = meses_disponibles[-3:]
    else:
        meses_sel = meses_disponibles[-3:]

    # Para cada mes seleccionado, obtener compras y sus items
    def rango_mes(d):
        if d.month == 12:
            fin = date(d.year + 1, 1, 1)
        else:
            fin = date(d.year, d.month + 1, 1)
        return d, fin - timedelta(days=1)

    # ── Recopilar datos por mes ──
    datos_mes = {}  # {date: {total, n_compras, items: {descripcion: {cant, monto, precio_prom}}}}
    for mes in meses_sel:
        inicio, fin = rango_mes(mes)
        compras_mes = Compra.query.filter(
            Compra.fecha >= inicio,
            Compra.fecha <= fin,
            Compra.estado != 'anulado'
        ).all()
        total_mes = sum(c.total for c in compras_mes)
        items_mes = {}
        for c in compras_mes:
            for it in c.items:
                key = it.descripcion.strip().upper()
                if key not in items_mes:
                    items_mes[key] = {
                        'descripcion': it.descripcion.strip(),
                        'unidad': it.unidad or '',
                        'cantidad': 0, 'monto': 0,
                        'precios': []
                    }
                items_mes[key]['cantidad'] += it.cantidad
                items_mes[key]['monto']    += it.subtotal
                if it.precio_unitario:
                    items_mes[key]['precios'].append(it.precio_unitario)
        # Calcular precio promedio por item
        for k in items_mes:
            p = items_mes[k]['precios']
            items_mes[k]['precio_prom'] = round(sum(p) / len(p), 4) if p else 0
            items_mes[k]['monto'] = round(items_mes[k]['monto'], 2)

        datos_mes[mes] = {
            'total': round(total_mes, 2),
            'n_compras': len(compras_mes),
            'productos': items_mes
        }

    # ── Productos que aparecen en al menos 2 meses (para comparación) ──
    todos_items = set()
    for m in meses_sel:
        todos_items.update(datos_mes[m]['productos'].keys())

    # Construir tabla comparativa
    tabla = []
    for key in sorted(todos_items):
        fila = {'key': key, 'meses': {}}
        apariciones = 0
        for mes in meses_sel:
            item = datos_mes[mes]['productos'].get(key)
            fila['meses'][mes] = item
            if item:
                apariciones += 1

        # Calcular variación entre primer y último mes con dato
        precios_con_dato = [
            datos_mes[m]['productos'][key]['precio_prom']
            for m in meses_sel
            if key in datos_mes[m]['productos'] and datos_mes[m]['productos'][key]['precio_prom'] > 0
        ]
        if len(precios_con_dato) >= 2:
            p_inicial = precios_con_dato[0]
            p_final   = precios_con_dato[-1]
            fila['variacion'] = round((p_final - p_inicial) / p_inicial * 100, 1) if p_inicial else 0
        else:
            fila['variacion'] = None

        fila['apariciones'] = apariciones
        tabla.append(fila)

    # Ordenar: primero los que tienen variación, luego por nombre
    tabla.sort(key=lambda x: (x['variacion'] is None, x['key']))

    # Serie para gráfico de totales por mes
    serie_totales = {
        m.strftime('%b %Y'): datos_mes[m]['total']
        for m in meses_sel
    }

    return render_template('compras/costeo.html',
        meses_sel=meses_sel,
        meses_disponibles=meses_disponibles,
        datos_mes=datos_mes,
        tabla=tabla,
        serie_totales=serie_totales,
        hoy=hoy)