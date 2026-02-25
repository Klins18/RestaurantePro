import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
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

    # Serie diaria para gráfico
    serie_diaria = {}
    delta = hasta - desde
    for i in range(delta.days + 1):
        d = desde + timedelta(days=i)
        serie_diaria[d.strftime('%d/%m')] = 0
    for v in ventas:
        key = v.fecha.strftime('%d/%m')
        if key in serie_diaria:
            serie_diaria[key] += v.total

    return render_template('ventas/index.html',
        ventas=ventas, total_periodo=total_periodo, total_pax=total_pax,
        por_empresa=por_empresa, serie_diaria=serie_diaria,
        desde=desde_str, hasta=hasta_str,
        cierre_hoy=cierre_hoy, hoy=hoy)


# ──────────────────────────────────────────────────────────────
#  NUEVA VENTA
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
def nueva():
    if request.method == 'POST':
        fecha_str  = request.form.get('fecha', '')
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha = date.today()

        empresa_id = request.form.get('empresa_id') or None
        es_privado = request.form.get('es_privado') == '1'
        num_pax    = int(request.form.get('num_pax', 0) or 0)
        ruta       = request.form.get('ruta', '').strip()
        nombre_grupo = request.form.get('nombre_grupo', '').strip()

        # Precio buffet por empresa
        precio_buffet = 0.0
        if empresa_id:
            emp = EmpresaTuristica.query.get(empresa_id)
            if emp and emp.nombre == 'Peru Hop':
                precio_buffet = PRECIO_PERUHOP
            elif request.form.get('precio_buffet'):
                try:
                    precio_buffet = float(request.form.get('precio_buffet'))
                except:
                    precio_buffet = 0.0

        total_buffet = round(num_pax * precio_buffet, 2)
        total_items  = float(request.form.get('total_items', 0) or 0)
        descuento    = float(request.form.get('descuento', 0) or 0)
        subtotal     = round(total_buffet + total_items, 2)
        total        = round(subtotal - descuento, 2)

        venta = VentaDiaria(
            fecha=fecha,
            empresa_id=empresa_id,
            tipo_cliente='privado' if es_privado else 'empresa',
            nombre_grupo=nombre_grupo if es_privado else '',
            num_pax=num_pax,
            ruta=ruta,
            precio_buffet=precio_buffet,
            es_privado=es_privado,
            subtotal=subtotal,
            descuento=descuento,
            total=total,
            tipo_pago=request.form.get('tipo_pago', '') if es_privado else '',
            estado_pago='pagado' if es_privado else 'pendiente',
            observaciones=request.form.get('observaciones', ''),
            usuario_id=current_user.id,
            creado_en=now_peru()
        )
        db.session.add(venta)
        db.session.flush()

        # Items de bebidas
        prod_ids = request.form.getlist('item_producto_id[]')
        var_ids  = request.form.getlist('item_variante_id[]')
        descs    = request.form.getlist('item_desc[]')
        cants    = request.form.getlist('item_cant[]')
        precios  = request.form.getlist('item_precio[]')

        for i, desc in enumerate(descs):
            desc = desc.strip()
            if not desc:
                continue
            try:
                cant   = int(cants[i])   if cants[i]   else 1
                precio = float(precios[i]) if precios[i] else 0
            except:
                cant, precio = 1, 0
            subtotal_item = round(cant * precio, 2)
            p_carta_id    = int(prod_ids[i]) if i < len(prod_ids) and prod_ids[i] else None
            v_id          = int(var_ids[i])  if i < len(var_ids)  and var_ids[i]  else None

            item = ItemVenta(
                venta_id=venta.id,
                producto_carta_id=p_carta_id,
                variante_id=v_id,
                descripcion=desc,
                cantidad=cant,
                precio_unitario=precio,
                subtotal=subtotal_item
            )
            db.session.add(item)

            # ── Descontar del inventario almacén si el producto lo tiene configurado ──
            if p_carta_id:
                prod_carta = ProductoCarta.query.get(p_carta_id)
                if prod_carta and prod_carta.descuenta_inventario and prod_carta.producto_almacen_id:
                    prod_alm = Producto.query.get(prod_carta.producto_almacen_id)
                    if prod_alm:
                        prod_alm.stock_actual = max(0, (prod_alm.stock_actual or 0) - cant)
                        mov = MovimientoAlmacen(
                            tipo='egreso',
                            producto_id=prod_alm.id,
                            cantidad=cant,
                            motivo=f'Venta #{venta.id} — {desc}',
                            referencia=f'VENTA-{venta.id}',
                            usuario_id=current_user.id,
                            fecha_hora=now_peru()
                        )
                        db.session.add(mov)

        registrar_auditoria(current_user.id, 'NUEVA_VENTA', 'ventas_diarias', venta.id,
            f'Total: S/.{total:.2f} · Pax: {num_pax}', ip=request.remote_addr)
        db.session.commit()
        flash(f'Venta registrada. Total: S/.{total:.2f}', 'success')
        return redirect(url_for('ventas.ver', id=venta.id))

    from models import CategoriaCarta
    empresas   = EmpresaTuristica.query.filter_by(activo=True).order_by(EmpresaTuristica.nombre).all()
    categorias = CategoriaCarta.query.filter_by(activo=True).order_by(CategoriaCarta.orden).all()
    return render_template('ventas/nueva.html',
        empresas=empresas, categorias=categorias, hoy=date.today(),
        precio_peruhop=PRECIO_PERUHOP)


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