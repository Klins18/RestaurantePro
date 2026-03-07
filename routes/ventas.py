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
    """Pantalla de servicio: tabs por empresa, pedidos independientes, cierre conjunto."""
    if request.method == 'POST':
        fecha_str = request.form.get('fecha', '')
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha = date.today()

        # Recibimos JSON con todas las tabs: [{empresa_id, es_privado, nombre_grupo, tipo_pago, items:[...]}]
        import json
        tabs_json = request.form.get('tabs_json', '[]')
        try:
            tabs = json.loads(tabs_json)
        except:
            tabs = []

        if not tabs:
            flash('No hay pedidos para registrar.', 'error')
            return redirect(url_for('ventas.nueva'))

        ventas_creadas = []
        for tab in tabs:
            if not tab.get('items'):
                continue
            empresa_id = tab.get('empresa_id') or None
            if empresa_id:
                empresa_id = int(empresa_id)
            es_privado = bool(tab.get('es_privado', False))
            nombre_grupo = tab.get('nombre_grupo', '').strip()
            tipo_pago    = tab.get('tipo_pago', '')
            observaciones = tab.get('observaciones', '')

            total_items = sum(float(i['precio']) * int(i['cant']) for i in tab['items'])
            total = round(total_items, 2)

            venta = VentaDiaria(
                fecha=fecha,
                empresa_id=empresa_id,
                tipo_cliente='privado' if es_privado else 'empresa',
                nombre_grupo=nombre_grupo if es_privado else '',
                num_pax=0, ruta='', precio_buffet=0,
                es_privado=es_privado,
                subtotal=total, descuento=0, total=total,
                tipo_pago=tipo_pago if es_privado else '',
                estado_pago='pagado' if es_privado else 'pendiente',
                observaciones=observaciones,
                usuario_id=current_user.id,
                creado_en=now_peru()
            )
            db.session.add(venta)
            db.session.flush()

            for it in tab['items']:
                cant   = int(it.get('cant', 1))
                precio = float(it.get('precio', 0))
                p_carta_id = int(it['prod_id']) if it.get('prod_id') else None
                v_id       = int(it['var_id'])  if it.get('var_id')  else None
                db.session.add(ItemVenta(
                    venta_id=venta.id,
                    producto_carta_id=p_carta_id,
                    variante_id=v_id,
                    descripcion=it.get('nombre', ''),
                    cantidad=cant,
                    precio_unitario=precio,
                    subtotal=round(cant * precio, 2)
                ))
                if p_carta_id:
                    prod_carta = ProductoCarta.query.get(p_carta_id)
                    if prod_carta and prod_carta.descuenta_inventario and prod_carta.producto_almacen_id:
                        prod_alm = Producto.query.get(prod_carta.producto_almacen_id)
                        if prod_alm:
                            prod_alm.stock_actual = max(0, (prod_alm.stock_actual or 0) - cant)
                            db.session.add(MovimientoAlmacen(
                                tipo='egreso', producto_id=prod_alm.id, cantidad=cant,
                                motivo=f'Venta #{venta.id} — {it.get("nombre","")}',
                                referencia=f'VENTA-{venta.id}',
                                usuario_id=current_user.id, fecha_hora=now_peru()
                            ))
            registrar_auditoria(current_user.id, 'NUEVA_VENTA', 'ventas_diarias', venta.id,
                f'Total: S/.{total:.2f}', ip=request.remote_addr)
            ventas_creadas.append(venta)

        db.session.commit()
        n = len(ventas_creadas)
        if n == 1:
            flash(f'Venta registrada — S/.{ventas_creadas[0].total:.2f}', 'success')
            return redirect(url_for('ventas.ver', id=ventas_creadas[0].id))
        else:
            flash(f'{n} ventas registradas correctamente.', 'success')
            return redirect(url_for('ventas.index'))

    from models import CategoriaCarta
    hoy = date.today()
    empresas   = EmpresaTuristica.query.filter_by(activo=True).order_by(EmpresaTuristica.nombre).all()
    categorias = CategoriaCarta.query.filter_by(activo=True).order_by(CategoriaCarta.orden).all()
    return render_template('ventas/nueva.html',
        empresas=empresas, categorias=categorias, hoy=hoy,
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
