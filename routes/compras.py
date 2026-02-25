import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import login_required, current_user
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
def index():
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    proveedor_id = request.args.get('proveedor', '')
    estado = request.args.get('estado', '')

    q = Compra.query.order_by(Compra.fecha.desc(), Compra.creado_en.desc())
    if desde:
        try: q = q.filter(Compra.fecha >= datetime.strptime(desde, '%Y-%m-%d').date())
        except: pass
    if hasta:
        try: q = q.filter(Compra.fecha <= datetime.strptime(hasta, '%Y-%m-%d').date())
        except: pass
    if proveedor_id:
        q = q.filter_by(proveedor_id=int(proveedor_id))
    if estado:
        q = q.filter_by(estado=estado)

    compras = q.all()
    proveedores = Proveedor.query.filter_by(activo=True).order_by(Proveedor.nombre).all()
    total_periodo = sum(c.total for c in compras)

    return render_template('compras/index.html', compras=compras,
        proveedores=proveedores, total_periodo=total_periodo,
        desde=desde, hasta=hasta, prov_filtro=proveedor_id, estado_filtro=estado)


# ──────────────────────────────────────
#  NUEVA COMPRA
# ──────────────────────────────────────
@compras_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
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
    return render_template('compras/nueva.html',
        proveedores=proveedores, productos=productos, hoy=date.today())


# ──────────────────────────────────────
#  VER COMPRA
# ──────────────────────────────────────
@compras_bp.route('/<int:id>')
@login_required
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
