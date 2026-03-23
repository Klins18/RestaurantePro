import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import login_required, current_user
from routes.decorators import permiso_required
from models import db, ProductoRecurrente, EntregaDiaria, PagoProveedor, registrar_auditoria
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
import pytz

suministros_bp = Blueprint('suministros', __name__, url_prefix='/suministros')
PERU_TZ = pytz.timezone('America/Lima')
UPLOAD_FOLDER = 'static/uploads/vouchers'
ALLOWED = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

def guardar_voucher(file):
    if file and file.filename and '.' in file.filename:
        ext = file.filename.rsplit('.', 1)[1].lower()
        if ext in ALLOWED:
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S_')
            filename = ts + secure_filename(file.filename)
            file.save(os.path.join(UPLOAD_FOLDER, filename))
            return filename
    return None


# ────────────────────────────────────────
#  INICIO — lista de productos recurrentes
# ────────────────────────────────────────
@suministros_bp.route('/')
@login_required
@permiso_required('compras')
def index():
    productos = ProductoRecurrente.query.filter_by(activo=True).all()
    hoy = date.today()

    resumen = []
    for p in productos:
        # Entrega de hoy
        entrega_hoy = EntregaDiaria.query.filter_by(
            producto_id=p.id, fecha=hoy).first()
        # Total del mes actual
        inicio_mes = hoy.replace(day=1)
        entregas_mes = db.session.query(
            db.func.sum(EntregaDiaria.cantidad),
            db.func.sum(EntregaDiaria.subtotal)
        ).filter(
            EntregaDiaria.producto_id == p.id,
            EntregaDiaria.fecha >= inicio_mes,
            EntregaDiaria.fecha <= hoy
        ).first()
        # Último pago
        ultimo_pago = PagoProveedor.query.filter_by(
            producto_id=p.id
        ).order_by(PagoProveedor.periodo_hasta.desc()).first()
        # Acumulado desde último pago
        desde_pago = (ultimo_pago.periodo_hasta + timedelta(days=1)
                      if ultimo_pago else inicio_mes)
        acum = db.session.query(
            db.func.sum(EntregaDiaria.cantidad),
            db.func.sum(EntregaDiaria.subtotal)
        ).filter(
            EntregaDiaria.producto_id == p.id,
            EntregaDiaria.fecha >= desde_pago,
            EntregaDiaria.fecha <= hoy
        ).first()
        resumen.append({
            'producto':       p,
            'entrega_hoy':    entrega_hoy,
            'mes_cantidad':   round(entregas_mes[0] or 0, 2),
            'mes_monto':      round(entregas_mes[1] or 0, 2),
            'acum_cantidad':  round(acum[0] or 0, 2),
            'acum_monto':     round(acum[1] or 0, 2),
            'ultimo_pago':    ultimo_pago,
            'desde_pago':     desde_pago,
        })
    return render_template('suministros/index.html',
                           resumen=resumen, hoy=hoy)


# ────────────────────────────────────────
#  NUEVO PRODUCTO RECURRENTE
# ────────────────────────────────────────
@suministros_bp.route('/nuevo-producto', methods=['GET', 'POST'])
@login_required
@permiso_required('compras')
def nuevo_producto():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'error')
            return redirect(request.url)
        p = ProductoRecurrente(
            nombre=nombre,
            unidad=request.form.get('unidad', 'litros'),
            proveedor_nombre=request.form.get('proveedor_nombre', '').strip(),
            proveedor_tel=request.form.get('proveedor_tel', '').strip(),
            precio_unitario=float(request.form.get('precio_unitario', 0) or 0),
        )
        db.session.add(p)
        db.session.commit()
        flash(f'Producto "{nombre}" creado.', 'success')
        return redirect(url_for('suministros.index'))
    return render_template('suministros/nuevo_producto.html')


# ────────────────────────────────────────
#  REGISTRAR ENTREGA DEL DÍA
# ────────────────────────────────────────
@suministros_bp.route('/<int:pid>/entrega', methods=['POST'])
@login_required
@permiso_required('compras')
def registrar_entrega(pid):
    prod = ProductoRecurrente.query.get_or_404(pid)
    fecha_str = request.form.get('fecha', date.today().isoformat())
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except:
        fecha = date.today()

    cantidad = float(request.form.get('cantidad', 0) or 0)
    precio   = float(request.form.get('precio_unitario', prod.precio_unitario) or 0)

    existente = EntregaDiaria.query.filter_by(producto_id=pid, fecha=fecha).first()
    if existente:
        existente.cantidad       = cantidad
        existente.precio_unitario= precio
        existente.subtotal       = round(cantidad * precio, 2)
        existente.observaciones  = request.form.get('observaciones', '')
        flash(f'Entrega del {fecha.strftime("%d/%m")} actualizada: {cantidad} {prod.unidad}.', 'success')
    else:
        db.session.add(EntregaDiaria(
            producto_id=pid, fecha=fecha,
            cantidad=cantidad, precio_unitario=precio,
            subtotal=round(cantidad * precio, 2),
            observaciones=request.form.get('observaciones', ''),
            usuario_id=current_user.id, creado_en=now_peru()
        ))
        flash(f'Entrega registrada: {cantidad} {prod.unidad} de {prod.nombre}.', 'success')
    db.session.commit()
    return redirect(url_for('suministros.detalle', pid=pid))


# ────────────────────────────────────────
#  DETALLE / HISTORIAL DE UN PRODUCTO
# ────────────────────────────────────────
@suministros_bp.route('/<int:pid>')
@login_required
@permiso_required('compras')
def detalle(pid):
    prod = ProductoRecurrente.query.get_or_404(pid)
    hoy = date.today()

    # Rango a mostrar (por defecto mes actual)
    desde_str = request.args.get('desde', hoy.replace(day=1).isoformat())
    hasta_str = request.args.get('hasta', hoy.isoformat())
    try:
        desde = datetime.strptime(desde_str, '%Y-%m-%d').date()
        hasta = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except:
        desde = hoy.replace(day=1); hasta = hoy

    entregas = EntregaDiaria.query.filter(
        EntregaDiaria.producto_id == pid,
        EntregaDiaria.fecha >= desde,
        EntregaDiaria.fecha <= hasta
    ).order_by(EntregaDiaria.fecha.desc()).all()

    total_cantidad = sum(e.cantidad for e in entregas)
    total_monto    = sum(e.subtotal for e in entregas)

    # Pagos del producto
    pagos = PagoProveedor.query.filter_by(producto_id=pid).order_by(
        PagoProveedor.periodo_hasta.desc()).all()

    # Pendiente de pago (desde último pago hasta hoy)
    ultimo_pago = pagos[0] if pagos else None
    desde_pend = (ultimo_pago.periodo_hasta + timedelta(days=1)
                  if ultimo_pago else date(hoy.year, 1, 1))
    pend = db.session.query(
        db.func.sum(EntregaDiaria.cantidad),
        db.func.sum(EntregaDiaria.subtotal)
    ).filter(
        EntregaDiaria.producto_id == pid,
        EntregaDiaria.fecha >= desde_pend,
        EntregaDiaria.fecha <= hoy
    ).first()
    pend_cantidad = round(pend[0] or 0, 2)
    pend_monto    = round(pend[1] or 0, 2)

    return render_template('suministros/detalle.html',
        prod=prod, entregas=entregas, hoy=hoy,
        total_cantidad=total_cantidad, total_monto=total_monto,
        pagos=pagos, pend_cantidad=pend_cantidad, pend_monto=pend_monto,
        desde_pend=desde_pend,
        desde=desde_str, hasta=hasta_str)


# ────────────────────────────────────────
#  ELIMINAR ENTREGA
# ────────────────────────────────────────
@suministros_bp.route('/entrega/<int:eid>/eliminar', methods=['POST'])
@login_required
@permiso_required('compras')
def eliminar_entrega(eid):
    e = EntregaDiaria.query.get_or_404(eid)
    pid = e.producto_id
    db.session.delete(e)
    db.session.commit()
    flash('Entrega eliminada.', 'success')
    return redirect(url_for('suministros.detalle', pid=pid))


# ────────────────────────────────────────
#  REGISTRAR PAGO AL PROVEEDOR
# ────────────────────────────────────────
@suministros_bp.route('/<int:pid>/pago', methods=['POST'])
@login_required
@permiso_required('compras')
def registrar_pago(pid):
    prod = ProductoRecurrente.query.get_or_404(pid)
    archivo = guardar_voucher(request.files.get('archivo_voucher'))

    try:
        desde = datetime.strptime(request.form['periodo_desde'], '%Y-%m-%d').date()
        hasta = datetime.strptime(request.form['periodo_hasta'], '%Y-%m-%d').date()
    except:
        flash('Fechas de período inválidas.', 'error')
        return redirect(url_for('suministros.detalle', pid=pid))

    # Calcular acumulado del período
    acum = db.session.query(
        db.func.sum(EntregaDiaria.cantidad),
        db.func.sum(EntregaDiaria.subtotal)
    ).filter(
        EntregaDiaria.producto_id == pid,
        EntregaDiaria.fecha >= desde,
        EntregaDiaria.fecha <= hasta
    ).first()
    cant_total = round(acum[0] or 0, 2)
    monto_total = round(acum[1] or 0, 2)
    monto_pagado = float(request.form.get('monto_pagado', monto_total) or monto_total)
    fecha_pago_str = request.form.get('fecha_pago', '')
    try:
        fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d').date()
    except:
        fecha_pago = date.today()

    pago = PagoProveedor(
        producto_id=pid,
        periodo_desde=desde,
        periodo_hasta=hasta,
        cantidad_total=cant_total,
        monto_total=monto_total,
        monto_pagado=monto_pagado,
        tipo_pago=request.form.get('tipo_pago', 'efectivo'),
        fecha_pago=fecha_pago,
        archivo_voucher=archivo,
        observaciones=request.form.get('observaciones', ''),
        estado='pagado',
        usuario_id=current_user.id,
        creado_en=now_peru()
    )
    db.session.add(pago)
    registrar_auditoria(current_user.id, 'PAGO_PROVEEDOR', 'pagos_proveedor', None,
        f'{prod.nombre} | S/.{monto_pagado:.2f} | {desde}→{hasta}',
        ip=request.remote_addr)
    db.session.commit()
    flash(f'Pago registrado: S/.{monto_pagado:.2f} por {cant_total} {prod.unidad} '
          f'({desde.strftime("%d/%m")} al {hasta.strftime("%d/%m/%Y")}).', 'success')
    return redirect(url_for('suministros.detalle', pid=pid))


# ────────────────────────────────────────
#  DESCARGAR VOUCHER
# ────────────────────────────────────────
@suministros_bp.route('/voucher/<filename>')
@login_required
def voucher(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)
