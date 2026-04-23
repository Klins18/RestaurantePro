import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import (db, VentaDiaria, ItemVenta, EmpresaTuristica, ProductoCarta,
                    VarianteCarta, KardexComedor, CierreCaja, Producto,
                    MovimientoAlmacen, registrar_auditoria)
from sqlalchemy import func
from datetime import datetime, date, timedelta
import pytz

ventas_bp = Blueprint('ventas', __name__, url_prefix='/ventas')
PERU_TZ = pytz.timezone('America/Lima')
PRECIO_PERUHOP = 35.0   # S/. por pax

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)


# ──────────────────────────────────────────────────────────────
#  DASHBOARD
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/')
@login_required
def index():
    hoy = date.today()
    desde_str = request.args.get('desde', hoy.strftime('%Y-%m-%d'))
    hasta_str = request.args.get('hasta',  hoy.strftime('%Y-%m-%d'))
    try:
        desde = datetime.strptime(desde_str, '%Y-%m-%d').date()
        hasta = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except:
        desde = hasta = hoy

    ventas = VentaDiaria.query.filter(
        VentaDiaria.fecha >= desde,
        VentaDiaria.fecha <= hasta
    ).order_by(VentaDiaria.fecha.desc(), VentaDiaria.creado_en.desc()).all()

    total_periodo = sum(v.total for v in ventas)
    total_pax     = sum(v.num_pax or 0 for v in ventas)

    por_empresa = {}
    for v in ventas:
        key   = v.empresa.nombre if v.empresa else 'Privado'
        color = v.empresa.color  if v.empresa else '#10b981'
        if key not in por_empresa:
            por_empresa[key] = {'total': 0, 'ventas': 0, 'pax': 0, 'color': color}
        por_empresa[key]['total']  += v.total
        por_empresa[key]['ventas'] += 1
        por_empresa[key]['pax']    += v.num_pax or 0

    # Cierre del día
    cierre_hoy = CierreCaja.query.filter_by(fecha=hoy).first()

    # Serie diaria para gráfico (fecha → total)
    serie_diaria = {}
    for v in sorted(ventas, key=lambda x: x.fecha):
        k = v.fecha.strftime('%d/%m')
        serie_diaria[k] = round(serie_diaria.get(k, 0) + v.total, 2)

    # por_empresa necesita valores JSON-serializables (no Undefined)
    por_empresa_json = {
        k: {'total': float(v['total']), 'ventas': int(v['ventas']),
            'pax': int(v['pax']), 'color': str(v['color'])}
        for k, v in por_empresa.items()
    }

    return render_template('ventas/index.html',
        ventas=ventas, total_periodo=total_periodo, total_pax=total_pax,
        por_empresa=por_empresa_json, serie_diaria=serie_diaria,
        desde=desde_str, hasta=hasta_str,
        cierre_hoy=cierre_hoy, hoy=hoy)


# ──────────────────────────────────────────────────────────────
#  NUEVA VENTA
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
def nueva():
    if request.method == 'POST':
        import json as _json
        fecha_str = request.form.get('fecha', '')
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha = date.today()

        tabs_raw = request.form.get('tabs_json', '[]')
        try:
            tabs_data = _json.loads(tabs_raw)
        except Exception:
            flash('Error al leer los datos de la venta.', 'error')
            return redirect(url_for('ventas.nueva'))

        if not tabs_data:
            flash('No hay ítems para registrar.', 'error')
            return redirect(url_for('ventas.nueva'))

        ultima_venta = None
        ventas_registradas = 0

        for tab in tabs_data:
            empresa_id   = tab.get('empresa_id') or None
            es_privado   = bool(tab.get('es_privado', False))
            num_pax      = int(tab.get('num_pax', 0) or 0)
            precio_buffet= float(tab.get('precio_buffet', 0) or 0)
            nombre_grupo = str(tab.get('nombre_grupo', '') or '').strip()
            tipo_pago    = str(tab.get('tipo_pago', '') or '')
            items        = tab.get('items', [])

            total_items = sum(
                round(float(it.get('precio', 0)) * int(it.get('cant', 1)), 2)
                for it in items
            )
            total_buffet = round(num_pax * precio_buffet, 2)
            subtotal     = round(total_buffet + total_items, 2)
            total        = subtotal  # sin descuento por ahora

            es_cortesia = bool(tab.get('es_cortesia', False))
            # Si es cortesía, total = 0 (no genera ingreso)
            if es_cortesia:
                total_real = 0
                obs_extra = '[CORTESÍA/CONSUMO INTERNO] '
            else:
                total_real = total
                obs_extra = ''

            venta = VentaDiaria(
                fecha=fecha,
                empresa_id=empresa_id,
                tipo_cliente='cortesia' if es_cortesia else ('privado' if es_privado else 'empresa'),
                nombre_grupo=nombre_grupo,
                num_pax=num_pax,
                precio_buffet=precio_buffet,
                es_privado=es_privado,
                subtotal=subtotal if not es_cortesia else 0,
                descuento=0,
                total=total_real,
                tipo_pago=tipo_pago if es_privado else '',
                estado_pago='cortesia' if es_cortesia else ('pagado' if es_privado else 'pendiente'),
                observaciones=obs_extra + str(tab.get('observaciones', '') or ''),
                usuario_id=current_user.id,
                creado_en=now_peru()
            )
            db.session.add(venta)
            db.session.flush()

            for it in items:
                nombre_it  = str(it.get('nombre', '')).strip()
                if not nombre_it:
                    continue
                cant       = int(it.get('cant', 1) or 1)
                precio_it  = float(it.get('precio', 0) or 0)
                sub_it     = round(cant * precio_it, 2)
                p_carta_id = int(it['prod_id']) if it.get('prod_id') else None
                v_id       = int(it['var_id'])  if it.get('var_id')  else None

                db.session.add(ItemVenta(
                    venta_id=venta.id,
                    producto_carta_id=p_carta_id,
                    variante_id=v_id,
                    descripcion=nombre_it,
                    cantidad=cant,
                    precio_unitario=precio_it,
                    # Cortesía: subtotal=0 para que no cuente en ingresos
                    subtotal=0 if es_cortesia else sub_it
                ))

                # Descontar inventario si aplica
                if p_carta_id:
                    pc = ProductoCarta.query.get(p_carta_id)
                    if pc and pc.descuenta_inventario and pc.producto_almacen_id:
                        pa = Producto.query.get(pc.producto_almacen_id)
                        if pa:
                            pa.stock_actual = max(0, (pa.stock_actual or 0) - cant)
                            db.session.add(MovimientoAlmacen(
                                tipo='egreso', producto_id=pa.id, cantidad=cant,
                                motivo=f'Venta #{venta.id} — {nombre_it}',
                                referencia=f'VENTA-{venta.id}',
                                usuario_id=current_user.id, fecha_hora=now_peru()
                            ))

            registrar_auditoria(current_user.id, 'NUEVA_VENTA', 'ventas_diarias', venta.id,
                f'Total: S/.{total:.2f} · Pax: {num_pax}', ip=request.remote_addr)
            ultima_venta = venta
            ventas_registradas += 1

        db.session.commit()
        if ventas_registradas == 1:
            flash(f'Venta registrada correctamente. Total: S/.{ultima_venta.total:.2f}', 'success')
            return redirect(url_for('ventas.ver', id=ultima_venta.id))
        else:
            flash(f'{ventas_registradas} ventas registradas correctamente.', 'success')
            return redirect(url_for('ventas.index'))

    from models import CategoriaCarta
    from flask import make_response as _mkr
    empresas   = EmpresaTuristica.query.filter_by(activo=True).order_by(EmpresaTuristica.nombre).all()
    categorias = CategoriaCarta.query.filter_by(activo=True).order_by(CategoriaCarta.orden).all()
    resp = _mkr(render_template('ventas/nueva.html',
        empresas=empresas, categorias=categorias, hoy=date.today(),
        precio_peruhop=PRECIO_PERUHOP))
    # No-cache: evita que el botón Atrás muestre la página en caché con datos viejos
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ──────────────────────────────────────────────────────────────
#  VER VENTA
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/<int:id>')
@login_required
def ver(id):
    venta = VentaDiaria.query.get_or_404(id)
    return render_template('ventas/ver.html', venta=venta)


# ──────────────────────────────────────────────────────────────
#  CIERRE DE CAJA DIARIO
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/cierre', methods=['GET', 'POST'])
@login_required
@permiso_required('cierre_caja')
def cierre():
    hoy = date.today()
    fecha_str = request.args.get('fecha', hoy.strftime('%Y-%m-%d'))
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except:
        fecha = hoy

    if request.method == 'POST':
        fecha_post = request.form.get('fecha', fecha_str)
        try:
            fecha = datetime.strptime(fecha_post, '%Y-%m-%d').date()
        except:
            fecha = hoy

        efectivo      = float(request.form.get('efectivo', 0)      or 0)
        tarjeta       = float(request.form.get('tarjeta', 0)       or 0)
        yape          = float(request.form.get('yape', 0)          or 0)
        transferencia = float(request.form.get('transferencia', 0) or 0)
        total_cobrado = round(efectivo + tarjeta + yape + transferencia, 2)

        cierre_exist = CierreCaja.query.filter_by(fecha=fecha).first()
        if cierre_exist:
            cierre_exist.efectivo      = efectivo
            cierre_exist.tarjeta       = tarjeta
            cierre_exist.yape          = yape
            cierre_exist.transferencia = transferencia
            cierre_exist.total_cobrado = total_cobrado
            cierre_exist.observaciones = request.form.get('observaciones', '')
            cierre_exist.usuario_id    = current_user.id
            cierre_exist.creado_en     = now_peru()
        else:
            c = CierreCaja(
                fecha=fecha,
                efectivo=efectivo, tarjeta=tarjeta,
                yape=yape, transferencia=transferencia,
                total_cobrado=total_cobrado,
                observaciones=request.form.get('observaciones', ''),
                usuario_id=current_user.id,
                creado_en=now_peru()
            )
            db.session.add(c)

        db.session.commit()
        flash(f'Cierre de caja guardado. Total cobrado: S/.{total_cobrado:.2f}', 'success')
        return redirect(url_for('ventas.cierre', fecha=fecha.strftime('%Y-%m-%d')))

    # Ventas del día seleccionado
    ventas_dia = VentaDiaria.query.filter_by(fecha=fecha).all()
    total_ventas = sum(v.total for v in ventas_dia)
    total_pax    = sum(v.num_pax or 0 for v in ventas_dia)
    cierre_exist = CierreCaja.query.filter_by(fecha=fecha).first()

    return render_template('ventas/cierre.html',
        fecha=fecha, ventas_dia=ventas_dia,
        total_ventas=total_ventas, total_pax=total_pax,
        cierre=cierre_exist, hoy=hoy)


# ──────────────────────────────────────────────────────────────
#  PASAJEROS POR DÍA (registro de empresas y rutas)
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
#  EDITAR / ELIMINAR ITEMS DE VENTA (antes del cierre de caja)
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/item/<int:item_id>/editar', methods=['POST'])
@login_required
def editar_item_venta(item_id):
    item  = ItemVenta.query.get_or_404(item_id)
    venta = item.venta
    # Solo si NO hay cierre de caja del día
    cierre = CierreCaja.query.filter_by(fecha=venta.fecha).first()
    if cierre:
        flash('No se puede editar: la caja de este día ya está cerrada.', 'error')
        return redirect(url_for('ventas.index'))

    try:
        nueva_cant  = float(request.form.get('cantidad', item.cantidad))
        nuevo_precio = float(request.form.get('precio_unit', item.precio_unit or 0))
    except:
        flash('Datos inválidos.', 'error')
        return redirect(url_for('ventas.index'))

    item.cantidad   = nueva_cant
    item.precio_unit = nuevo_precio
    item.subtotal   = round(nueva_cant * nuevo_precio, 2)

    # Recalcular total de la venta
    venta.total = round(sum(it.subtotal for it in venta.items), 2)
    db.session.commit()
    flash('Item actualizado.', 'success')
    return redirect(url_for('ventas.index'))


@ventas_bp.route('/item/<int:item_id>/eliminar', methods=['POST'])
@login_required
def eliminar_item_venta(item_id):
    item  = ItemVenta.query.get_or_404(item_id)
    venta = item.venta
    cierre = CierreCaja.query.filter_by(fecha=venta.fecha).first()
    if cierre:
        flash('No se puede eliminar: la caja de este día ya está cerrada.', 'error')
        return redirect(url_for('ventas.index'))

    # Devolver stock si el producto descuenta inventario
    if item.producto_carta_id:
        from models import ProductoCarta, Producto as ProdAlm
        pc = ProductoCarta.query.get(item.producto_carta_id)
        if pc and pc.descuenta_inventario and pc.producto_almacen_id:
            prod = ProdAlm.query.get(pc.producto_almacen_id)
            if prod:
                prod.stock_actual = (prod.stock_actual or 0) + item.cantidad

    nombre = item.descripcion
    db.session.delete(item)
    # Recalcular total
    db.session.flush()
    venta.total = round(sum(it.subtotal for it in venta.items), 2)
    db.session.commit()
    flash(f'"{nombre}" eliminado de la venta.', 'success')
    return redirect(url_for('ventas.index'))


@ventas_bp.route('/<int:id>/eliminar-venta', methods=['POST'])
@login_required
def eliminar_venta(id):
    venta  = VentaDiaria.query.get_or_404(id)
    cierre = CierreCaja.query.filter_by(fecha=venta.fecha).first()
    if cierre:
        flash('No se puede eliminar: la caja ya está cerrada.', 'error')
        return redirect(url_for('ventas.index'))
    # Devolver stock de todos los items
    from models import ProductoCarta, Producto as ProdAlm
    for item in venta.items:
        if item.producto_carta_id:
            pc = ProductoCarta.query.get(item.producto_carta_id)
            if pc and pc.descuenta_inventario and pc.producto_almacen_id:
                prod = ProdAlm.query.get(pc.producto_almacen_id)
                if prod:
                    prod.stock_actual = (prod.stock_actual or 0) + item.cantidad
    db.session.delete(venta)
    db.session.commit()
    flash('Venta eliminada y stock revertido.', 'success')
    return redirect(url_for('ventas.index'))

@ventas_bp.route('/pasajeros', methods=['GET', 'POST'])
@login_required
def pasajeros():
    """Registro de pasajeros por empresa y ruta del día"""
    hoy = date.today()
    fecha_str = request.args.get('fecha', hoy.strftime('%Y-%m-%d'))
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except:
        fecha = hoy

    ventas_dia = VentaDiaria.query.filter_by(fecha=fecha)\
        .order_by(VentaDiaria.creado_en).all()

    empresas = EmpresaTuristica.query.filter_by(activo=True).order_by(EmpresaTuristica.nombre).all()
    return render_template('ventas/pasajeros.html',
        fecha=fecha, ventas_dia=ventas_dia, empresas=empresas, hoy=hoy)


# ──────────────────────────────────────────────────────────────
#  API: variantes de producto
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/api/variantes/<int:producto_id>')
@login_required
def api_variantes(producto_id):
    producto = ProductoCarta.query.get_or_404(producto_id)
    variantes = [{'id': v.id, 'nombre': v.nombre} for v in producto.variantes if v.activo]
    return jsonify({
        'precio':   producto.precio,
        'variantes': variantes,
        'nombre':   producto.nombre
    })


# ──────────────────────────────────────────────────────────────
#  API: productos carta como JSON (para imagen placeholder)
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/api/carta')
@login_required
def api_carta():
    from models import CategoriaCarta
    cats = CategoriaCarta.query.filter_by(activo=True).order_by(CategoriaCarta.orden).all()
    result = []
    for cat in cats:
        prods = []
        for p in sorted(cat.productos, key=lambda x: x.orden):
            if p.activo:
                prods.append({
                    'id': p.id, 'nombre': p.nombre, 'precio': p.precio,
                    'tiene_variantes': p.tiene_variantes,
                    'descuenta_inventario': p.descuenta_inventario,
                    'variantes': [{'id': v.id, 'nombre': v.nombre}
                                  for v in p.variantes if v.activo]
                })
        result.append({'id': cat.id, 'nombre': cat.nombre, 'productos': prods})
    return jsonify(result)
