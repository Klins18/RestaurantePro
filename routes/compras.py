import os
import math
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, Compra, ItemCompra, Proveedor, Producto, MovimientoAlmacen, registrar_auditoria
from datetime import datetime, date
from sqlalchemy import func
from sqlalchemy.orm import joinedload
import pytz
from werkzeug.utils import secure_filename
from services.kardex import registrar_kardex
from services.units import UNIT_CHOICES, normalize_unit

compras_bp = Blueprint('compras', __name__, url_prefix='/compras')
PERU_TZ = pytz.timezone('America/Lima')
UPLOAD_FOLDER = 'uploads/comprobantes'
ALLOWED = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED

def guardar_archivo(file):
    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        folder = os.path.join(current_app.instance_path, UPLOAD_FOLDER)
        os.makedirs(folder, exist_ok=True)
        filename = f'{uuid.uuid4().hex}.{ext}'
        path = os.path.join(folder, filename)
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
    hoy = now_peru().date()
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

    total_compras = q.count()
    con_archivo_count = q.filter(Compra.archivo_comprobante.isnot(None), Compra.archivo_comprobante != '').count()
    sin_archivo_count = q.filter((Compra.archivo_comprobante.is_(None)) | (Compra.archivo_comprobante == '')).count()
    total_periodo = q.with_entities(func.coalesce(func.sum(Compra.total), 0)).scalar() or 0
    pagina = q.options(joinedload(Compra.proveedor)).paginate(
        page=request.args.get('page', 1, type=int), per_page=50, error_out=False
    )
    compras = pagina.items

    return render_template('compras/index.html', compras=compras,
        total_periodo=total_periodo, desde=desde_str, hasta=hasta_str,
        tipo=tipo, q=q_str, con_archivo=con_arch,
        pagina=pagina, total_compras=total_compras,
        con_archivo_count=con_archivo_count, sin_archivo_count=sin_archivo_count)


# ──────────────────────────────────────
#  NUEVA COMPRA
# ──────────────────────────────────────
@compras_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
@permiso_required('compras')
def nueva():
    if request.method == 'POST':
        fecha_str = request.form.get('fecha', '')
        fecha_pago_str = request.form.get('fecha_pago', '')
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha = now_peru().date()
        try:
            fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d').date() if fecha_pago_str else None
        except:
            fecha_pago = None

        descripciones = request.form.getlist('item_desc[]')
        cantidades = request.form.getlist('item_cant[]')
        unidades = request.form.getlist('item_unidad[]')
        precios = request.form.getlist('item_precio[]')
        producto_ids = request.form.getlist('item_producto_id[]')
        items_validos = []
        try:
            igv = float(request.form.get('igv', 0) or 0)
            if igv < 0 or not math.isfinite(igv):
                raise ValueError
            for i, desc in enumerate(descripciones):
                desc = desc.strip()
                if not desc:
                    continue
                cant = float(cantidades[i]) if i < len(cantidades) and cantidades[i] else 0
                precio = float(precios[i]) if i < len(precios) and precios[i] else 0
                if cant <= 0 or precio < 0 or not all(map(math.isfinite, (cant, precio))):
                    raise ValueError
                prod_id = int(producto_ids[i]) if i < len(producto_ids) and producto_ids[i] else None
                prod = db.session.get(Producto, prod_id) if prod_id else None
                if prod_id and not prod:
                    raise ValueError
                unidad = normalize_unit(unidades[i] if i < len(unidades) else '')
                if prod:
                    unidad_producto = normalize_unit(prod.unidad_medida)
                    if unidad and unidad != unidad_producto:
                        flash(
                            f'La unidad de "{prod.nombre}" es {unidad_producto}. '
                            'No se puede ingresar con otra unidad sin una conversión definida.',
                            'error',
                        )
                        return redirect(url_for('compras.nueva'))
                    unidad = unidad_producto
                items_validos.append((desc, cant, precio, prod_id, unidad))
            if not items_validos:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            flash('Revisa los artículos: se requiere una cantidad válida mayor que cero y precios no negativos.', 'error')
            return redirect(url_for('compras.nueva'))

        total_lineas = round(sum(cant * precio for _, cant, precio, _, _ in items_validos), 2)
        # En el formulario, IGV solo tiene valor cuando se marcó que los precios
        # ya lo incluyen. Por eso se separa del subtotal, no se suma otra vez.
        if igv > total_lineas:
            flash('El IGV no puede ser mayor que el total de los artículos.', 'error')
            return redirect(url_for('compras.nueva'))
        subtotal = round(total_lineas - igv, 2)
        total = total_lineas
        if not math.isfinite(total):
            flash('El total de la compra excede el rango permitido.', 'error')
            return redirect(url_for('compras.nueva'))
        proveedor_id_raw = request.form.get('proveedor_id', '').strip()
        proveedor = None
        if proveedor_id_raw:
            try:
                proveedor = db.session.get(Proveedor, int(proveedor_id_raw))
            except (TypeError, ValueError, OverflowError):
                proveedor = None
        if proveedor_id_raw and not proveedor:
            flash('El proveedor seleccionado ya no está disponible. Vuelve a elegirlo.', 'error')
            return redirect(url_for('compras.nueva'))
        proveedor_nombre = proveedor.nombre if proveedor else request.form.get('proveedor_nombre', '').strip()
        archivo = guardar_archivo(request.files.get('archivo_comprobante'))

        compra = Compra(
            fecha=fecha,
            proveedor_id=proveedor.id if proveedor else None,
            proveedor_nombre=proveedor_nombre,
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
        for desc, cant, precio, prod_id, unidad in items_validos:
            subtotal_item = round(cant * precio, 2)

            item = ItemCompra(
                compra_id=compra.id,
                producto_id=prod_id or None,
                descripcion=desc,
                cantidad=cant,
                unidad=unidad,
                precio_unitario=precio,
                subtotal=subtotal_item
            )
            db.session.add(item)
            db.session.flush()

            # Si está vinculado a un producto, actualizar stock y kardex
            if prod_id:
                prod = db.session.get(Producto, prod_id)
                if prod:
                    if precio > 0:
                        prod.costo_unitario = precio
                    referencia_mov = f'COMPRA-{compra.id}-ITEM-{item.id}'
                    db.session.add(MovimientoAlmacen(
                        tipo='ingreso', producto_id=prod.id, cantidad=cant,
                        unidad_medida=unidad,
                        motivo=f'Compra #{compra.id}: {desc}',
                        referencia=referencia_mov,
                        proveedor_id=compra.proveedor_id,
                        usuario_id=current_user.id,
                        fecha_hora=datetime.combine(fecha, datetime.min.time()),
                    ))
                    registrar_kardex(
                        prod.id, 'ingreso', cant, current_user.id,
                        concepto=f"Compra - {compra.tipo_comprobante or ''} {compra.serie_comprobante or ''}-{compra.numero_comprobante or ''}".strip(),
                        referencia=referencia_mov,
                        fecha=datetime.combine(fecha, datetime.min.time()),
                        precio_unitario=precio, compra_id=compra.id,
                    )
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
        {
            'id': p.id,
            'nombre': p.nombre,
            'unidad': normalize_unit(p.unidad_medida),
            'categoria': p.categoria.nombre if p.categoria else 'Sin categoría',
            'stock': p.stock_actual or 0,
        }
        for p in productos
    ]
    return render_template('compras/nueva.html',
        proveedores=proveedores, productos=productos,
        productos_json=productos_json, hoy=now_peru().date(), unidad_options=UNIT_CHOICES)


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
@permiso_required('compras')
def archivo(filename):
    safe_name = secure_filename(filename)
    private_folder = os.path.join(current_app.instance_path, UPLOAD_FOLDER)
    legacy_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'comprobantes')
    folder = private_folder if os.path.isfile(os.path.join(private_folder, safe_name)) else legacy_folder
    return send_from_directory(folder, safe_name, as_attachment=False)


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
    if compra.estado == 'anulado':
        flash('Esta compra ya estaba anulada.', 'warning')
        return redirect(url_for('compras.ver', id=id))

    cantidades_por_producto = {}
    for item in compra.items:
        if item.producto_id:
            cantidades_por_producto[item.producto_id] = (
                cantidades_por_producto.get(item.producto_id, 0) + (item.cantidad or 0)
            )
    for producto_id, cantidad in cantidades_por_producto.items():
        producto = db.session.get(Producto, producto_id)
        if producto and (producto.stock_actual or 0) < cantidad:
            flash(
                f'No se puede anular: quedan {producto.stock_actual or 0} '
                f'{producto.unidad_medida} de "{producto.nombre}" y la compra agregó {cantidad}. '
                'Regulariza el inventario antes de anularla.',
                'error',
            )
            return redirect(url_for('compras.ver', id=id))

    for item in compra.items:
        if not item.producto_id:
            continue
        producto = db.session.get(Producto, item.producto_id)
        if not producto:
            continue
        producto.stock_actual = (producto.stock_actual or 0) - (item.cantidad or 0)
        referencia = f'COMPRA-{compra.id}-ANULACION-ITEM-{item.id}'
        db.session.add(MovimientoAlmacen(
            tipo='egreso', producto_id=producto.id,
            cantidad=item.cantidad, unidad_medida=item.unidad,
            motivo=f'Anulación de compra #{compra.id}: {item.descripcion}',
            referencia=referencia, proveedor_id=compra.proveedor_id,
            usuario_id=current_user.id, fecha_hora=now_peru(),
        ))
        registrar_kardex(
            producto.id, 'egreso', item.cantidad, current_user.id,
            concepto=f'Anulación de compra #{compra.id}: {item.descripcion}',
            referencia=referencia, fecha=now_peru(),
        )
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
    hoy = now_peru().date()

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

    hoy = now_peru().date()

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
