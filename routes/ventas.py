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

    from sqlalchemy.orm import joinedload
    # joinedload evita N+1: carga empresa en la misma query
    ventas = VentaDiaria.query.options(
        joinedload(VentaDiaria.empresa)
    ).filter(
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

            venta = VentaDiaria(
                fecha=fecha,
                empresa_id=empresa_id,
                tipo_cliente='privado' if es_privado else 'empresa',
                nombre_grupo=nombre_grupo,
                num_pax=num_pax,
                precio_buffet=precio_buffet,
                es_privado=es_privado,
                subtotal=subtotal,
                descuento=0,
                total=total,
                tipo_pago=tipo_pago if es_privado else '',
                estado_pago='pagado' if es_privado else 'pendiente',
                observaciones=str(tab.get('observaciones', '') or ''),
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
                    subtotal=sub_it
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

# ──────────────────────────────────────
#  REPORTE MENSUAL DE GRUPOS PRIVADOS
# ──────────────────────────────────────
@ventas_bp.route('/privados')
@login_required
def privados():
    hoy = date.today()
    mes_str  = request.args.get('mes',  hoy.strftime('%Y-%m'))
    try:
        anio, mes = int(mes_str.split('-')[0]), int(mes_str.split('-')[1])
    except:
        anio, mes = hoy.year, hoy.month

    inicio = date(anio, mes, 1)
    if mes == 12:
        fin = date(anio + 1, 1, 1)
    else:
        fin = date(anio, mes + 1, 1)

    # Ventas privadas del mes
    ventas = VentaDiaria.query.filter(
        VentaDiaria.fecha >= inicio,
        VentaDiaria.fecha < fin,
        VentaDiaria.tipo_cliente == 'privado'
    ).order_by(VentaDiaria.fecha, VentaDiaria.creado_en).all()

    # Calcular totales
    total_grupos   = len(ventas)
    total_pax      = sum(v.num_pax or 0 for v in ventas)
    total_ingresos = sum(v.total or 0 for v in ventas)
    total_buffet   = sum((v.num_pax or 0) * (v.precio_buffet or 0) for v in ventas)
    total_consumo  = sum(
        sum(it.subtotal or 0 for it in v.items) for v in ventas
    )

    # Por método de pago
    por_pago = {}
    for v in ventas:
        k = v.tipo_pago or 'sin especificar'
        por_pago[k] = round(por_pago.get(k, 0) + v.total, 2)

    # Serie por día para gráfico
    serie_dia = {}
    for v in ventas:
        k = v.fecha.strftime('%d/%m')
        serie_dia[k] = round(serie_dia.get(k, 0) + v.total, 2)

    # Meses disponibles (últimos 12)
    meses = []
    d = date(hoy.year, hoy.month, 1)
    for _ in range(12):
        meses.append(d)
        d = date(d.year if d.month > 1 else d.year - 1,
                 d.month - 1 if d.month > 1 else 12, 1)
    meses.reverse()

    return render_template('ventas/privados.html',
        ventas=ventas, mes_actual=inicio, meses=meses,
        total_grupos=total_grupos, total_pax=total_pax,
        total_ingresos=total_ingresos, total_buffet=total_buffet,
        total_consumo=total_consumo, por_pago=por_pago,
        serie_dia=serie_dia, hoy=hoy)
