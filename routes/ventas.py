import os
import math
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import (db, VentaDiaria, ItemVenta, EmpresaTuristica, ProductoCarta,
                    VarianteCarta, CierreCaja, Producto,
                    MovimientoAlmacen, SolicitudVenta, registrar_auditoria)
from services.kardex import registrar_kardex
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError
from datetime import datetime, date, timedelta
import pytz

ventas_bp = Blueprint('ventas', __name__, url_prefix='/ventas')
PERU_TZ = pytz.timezone('America/Lima')
PRECIO_PERUHOP = 35.0   # S/. por pax


def registrar_ajuste_stock_venta(producto, cantidad, tipo, referencia, concepto):
    if cantidad <= 0:
        return
    producto.stock_actual = ((producto.stock_actual or 0) - cantidad) if tipo == 'egreso' \
        else (producto.stock_actual or 0) + cantidad
    db.session.add(MovimientoAlmacen(
        tipo=tipo, producto_id=producto.id, cantidad=cantidad,
        motivo=concepto, referencia=referencia,
        usuario_id=current_user.id, fecha_hora=now_peru(),
    ))
    registrar_kardex(
        producto.id, tipo, cantidad, current_user.id,
        concepto=concepto, referencia=referencia, fecha=now_peru(),
    )

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)


# ──────────────────────────────────────────────────────────────
#  DASHBOARD
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/')
@login_required
@permiso_required('ventas')
def index():
    hoy = now_peru().date()
    desde_str = request.args.get('desde', hoy.strftime('%Y-%m-%d'))
    hasta_str = request.args.get('hasta',  hoy.strftime('%Y-%m-%d'))
    try:
        desde = datetime.strptime(desde_str, '%Y-%m-%d').date()
        hasta = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except:
        desde = hasta = hoy

    q = VentaDiaria.query.filter(
        VentaDiaria.fecha >= desde,
        VentaDiaria.fecha <= hasta
    )

    resumen_total = q.with_entities(
        func.coalesce(func.sum(VentaDiaria.total), 0),
        func.coalesce(func.sum(VentaDiaria.num_pax), 0),
    ).one()
    total_periodo, total_pax = float(resumen_total[0]), int(resumen_total[1])

    por_empresa = {}
    grupos = db.session.query(
        EmpresaTuristica.nombre, EmpresaTuristica.color,
        func.coalesce(func.sum(VentaDiaria.total), 0),
        func.count(VentaDiaria.id), func.coalesce(func.sum(VentaDiaria.num_pax), 0),
    ).outerjoin(VentaDiaria.empresa).filter(
        VentaDiaria.fecha >= desde, VentaDiaria.fecha <= hasta
    ).group_by(EmpresaTuristica.id, EmpresaTuristica.nombre, EmpresaTuristica.color).all()
    for nombre, color, total, n_ventas, pax in grupos:
        key = nombre or 'Privado'
        por_empresa[key] = {'total': float(total), 'ventas': int(n_ventas),
                            'pax': int(pax), 'color': color or '#10b981'}

    # Cierre del día
    cierre_hoy = CierreCaja.query.filter_by(fecha=hoy).first()
    cierres_cerrados = {
        cierre_fecha for (cierre_fecha,) in db.session.query(CierreCaja.fecha).filter(
            CierreCaja.fecha >= desde,
            CierreCaja.fecha <= hasta,
            CierreCaja.abierta.is_(False),
        ).all()
    }

    # Serie diaria para gráfico (fecha → total)
    serie_diaria = {
        fecha_d.strftime('%d/%m'): round(float(total or 0), 2)
        for fecha_d, total in q.with_entities(
            VentaDiaria.fecha, func.sum(VentaDiaria.total)
        ).group_by(VentaDiaria.fecha).order_by(VentaDiaria.fecha).all()
    }

    # por_empresa necesita valores JSON-serializables (no Undefined)
    por_empresa_json = {k: {**v, 'color': str(v['color'])} for k, v in por_empresa.items()}

    pagina = q.options(joinedload(VentaDiaria.empresa), selectinload(VentaDiaria.items)).order_by(
        VentaDiaria.fecha.desc(), VentaDiaria.creado_en.desc()
    ).paginate(page=request.args.get('page', 1, type=int), per_page=50, error_out=False)

    return render_template('ventas/index.html',
        ventas=pagina.items, pagina=pagina, total_periodo=total_periodo, total_pax=total_pax,
        por_empresa=por_empresa_json, serie_diaria=serie_diaria,
        desde=desde_str, hasta=hasta_str,
        cierre_hoy=cierre_hoy, cierres_cerrados=cierres_cerrados, hoy=hoy)


# ──────────────────────────────────────────────────────────────
#  NUEVA VENTA
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
@permiso_required('ventas')
def nueva():
    if request.method == 'POST':
        import json as _json
        solicitud_token = request.form.get('solicitud_token', '').strip().lower()
        if len(solicitud_token) != 32 or any(char not in '0123456789abcdef' for char in solicitud_token):
            flash('No se pudo verificar el envío. Recarga el formulario y vuelve a intentarlo.', 'error')
            return redirect(url_for('ventas.nueva'))
        fecha_str = request.form.get('fecha', '')
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha = now_peru().date()

        def respuesta_duplicado(solicitud):
            if solicitud.usuario_id != current_user.id:
                flash('La solicitud ya fue procesada y no se puede volver a usar.', 'error')
                return redirect(url_for('ventas.index'))
            ventas_existentes = VentaDiaria.query.filter_by(
                solicitud_id=solicitud.id
            ).order_by(VentaDiaria.id).all()
            if not ventas_existentes:
                flash('El envío anterior quedó incompleto. Contacta a Administración antes de repetirlo.', 'error')
                return redirect(url_for('ventas.index'))
            flash('Este envío ya se había registrado. No se duplicó la venta.', 'info')
            if len(ventas_existentes) == 1:
                return redirect(url_for(
                    'ventas.ver', id=ventas_existentes[0].id,
                    venta_guardada=solicitud_token,
                ))
            fecha_solicitud = solicitud.fecha.isoformat()
            return redirect(url_for(
                'ventas.index', desde=fecha_solicitud, hasta=fecha_solicitud,
                venta_guardada=solicitud_token,
            ))

        solicitud_existente = SolicitudVenta.query.filter_by(token=solicitud_token).first()
        if solicitud_existente:
            return respuesta_duplicado(solicitud_existente)

        cierre_dia = CierreCaja.query.filter_by(fecha=fecha).with_for_update().first()
        if cierre_dia and not cierre_dia.abierta:
            flash('La caja de esa fecha está cerrada. Solicita a Administración que la reabra para registrar ventas.', 'error')
            return redirect(url_for('ventas.cierre', fecha=fecha.strftime('%Y-%m-%d')))

        tabs_raw = request.form.get('tabs_json', '[]')
        try:
            tabs_data = _json.loads(tabs_raw)
        except Exception:
            flash('Error al leer los datos de la venta.', 'error')
            return redirect(url_for('ventas.nueva'))

        if not tabs_data:
            flash('No hay ítems para registrar.', 'error')
            return redirect(url_for('ventas.nueva'))

        if not isinstance(tabs_data, list):
            flash('Formato de venta inválido.', 'error')
            return redirect(url_for('ventas.nueva'))

        requeridos = {}
        try:
            for tab in tabs_data:
                if not isinstance(tab, dict) or not isinstance(tab.get('items', []), list):
                    raise ValueError
                pax = int(tab.get('num_pax', 0) or 0)
                buffet = float(tab.get('precio_buffet', 0) or 0)
                if pax < 0 or buffet < 0 or not math.isfinite(buffet):
                    raise ValueError
                if not tab.get('items') and pax == 0:
                    raise ValueError
                empresa_id = tab.get('empresa_id') or None
                if empresa_id:
                    empresa_id = int(empresa_id)
                    empresa = db.session.get(EmpresaTuristica, empresa_id)
                    if not empresa or not empresa.activo:
                        raise ValueError
                    tab['empresa_id'] = empresa_id
                if not isinstance(tab.get('es_privado', False), bool) or not isinstance(tab.get('es_cortesia', False), bool):
                    raise ValueError
                tab['num_pax'], tab['precio_buffet'] = pax, buffet
                tab['items'] = tab.get('items', [])
                for it in tab['items']:
                    if not isinstance(it, dict):
                        raise ValueError
                    nombre_item = str(it.get('nombre', '')).strip()
                    if not nombre_item or len(nombre_item) > 200:
                        raise ValueError
                    it['nombre'] = nombre_item
                    cantidad = int(it.get('cant', 1) or 1)
                    precio = float(it.get('precio', 0) or 0)
                    if cantidad <= 0 or precio < 0 or not math.isfinite(precio):
                        raise ValueError
                    it['cant'], it['precio'] = cantidad, precio
                    producto_carta = None
                    if it.get('prod_id'):
                        producto_carta = db.session.get(ProductoCarta, int(it['prod_id']))
                        if not producto_carta or not producto_carta.activo:
                            raise ValueError
                        it['prod_id'] = producto_carta.id
                        if producto_carta.descuenta_inventario and producto_carta.producto_almacen_id:
                            requeridos[producto_carta.producto_almacen_id] = requeridos.get(producto_carta.producto_almacen_id, 0) + cantidad
                    if it.get('var_id'):
                        variante = db.session.get(VarianteCarta, int(it['var_id']))
                        if not variante or not variante.activo or not producto_carta or variante.producto_id != producto_carta.id:
                            raise ValueError
                        it['var_id'] = variante.id
        except (TypeError, ValueError, OverflowError):
            flash('Revisa cantidades, precios y productos: hay datos inválidos.', 'error')
            return redirect(url_for('ventas.nueva'))

        productos_bloqueados = {
            p.id: p for p in Producto.query.filter(Producto.id.in_(requeridos)).with_for_update().all()
        } if requeridos else {}
        for producto_id, cantidad in requeridos.items():
            producto = productos_bloqueados.get(producto_id)
            if not producto or (producto.stock_actual or 0) < cantidad:
                flash(f'Stock insuficiente para {producto.nombre if producto else "un producto"}. No se registró la venta.', 'error')
                return redirect(url_for('ventas.nueva'))

        solicitud_venta = SolicitudVenta(
            token=solicitud_token,
            fecha=fecha,
            usuario_id=current_user.id,
            creado_en=now_peru(),
        )
        db.session.add(solicitud_venta)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            solicitud_existente = SolicitudVenta.query.filter_by(token=solicitud_token).first()
            if solicitud_existente:
                return respuesta_duplicado(solicitud_existente)
            flash('No se pudo confirmar el registro. Revisa las ventas antes de volver a enviarlo.', 'error')
            return redirect(url_for('ventas.nueva'))

        ultima_venta = None
        ventas_registradas = 0

        for tab in tabs_data:
            empresa_id   = tab.get('empresa_id') or None
            es_privado   = bool(tab.get('es_privado', False))
            num_pax      = tab['num_pax']
            precio_buffet= tab['precio_buffet']
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
                solicitud_id=solicitud_venta.id,
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

            for item_index, it in enumerate(items, 1):
                nombre_it  = str(it.get('nombre', '')).strip()
                if not nombre_it:
                    continue
                cant       = int(it.get('cant', 1) or 1)
                precio_it  = float(it.get('precio', 0) or 0)
                sub_it     = round(cant * precio_it, 2)
                p_carta_id = int(it['prod_id']) if it.get('prod_id') else None
                v_id       = int(it['var_id'])  if it.get('var_id')  else None

                item_venta = ItemVenta(
                    venta_id=venta.id,
                    producto_carta_id=p_carta_id,
                    variante_id=v_id,
                    descripcion=nombre_it,
                    cantidad=cant,
                    precio_unitario=precio_it,
                    # Cortesía: subtotal=0 para que no cuente en ingresos
                    subtotal=0 if es_cortesia else sub_it
                )
                db.session.add(item_venta)

                # Descontar inventario si aplica
                if p_carta_id:
                    pc = db.session.get(ProductoCarta, p_carta_id)
                    if pc and pc.descuenta_inventario and pc.producto_almacen_id:
                        pa = db.session.get(Producto, pc.producto_almacen_id)
                        if pa:
                            referencia_mov = f'VENTA-{venta.id}-ITEM-{item_index}'
                            registrar_ajuste_stock_venta(
                                pa, cant, 'egreso', referencia_mov,
                                f'Venta #{venta.id} — {nombre_it}',
                            )

            registrar_auditoria(current_user.id, 'NUEVA_VENTA', 'ventas_diarias', venta.id,
                f'Total: S/.{total:.2f} · Pax: {num_pax}', ip=request.remote_addr)
            ultima_venta = venta
            ventas_registradas += 1

        db.session.commit()
        if ventas_registradas == 1:
            flash(f'Venta registrada correctamente. Total: S/.{ultima_venta.total:.2f}', 'success')
            return redirect(url_for('ventas.ver', id=ultima_venta.id, venta_guardada=solicitud_token))
        else:
            flash(f'{ventas_registradas} ventas registradas correctamente.', 'success')
            return redirect(url_for('ventas.index', desde=fecha.isoformat(), hasta=fecha.isoformat(), venta_guardada=solicitud_token))

    from models import CategoriaCarta
    from flask import make_response as _mkr
    hoy = now_peru().date()
    cierre_hoy = CierreCaja.query.filter_by(fecha=hoy).first()
    if cierre_hoy and not cierre_hoy.abierta:
        flash('La caja de hoy está cerrada. Administración debe reabrirla antes de registrar más ventas.', 'error')
        return redirect(url_for('ventas.cierre', fecha=hoy.strftime('%Y-%m-%d')))
    empresas   = EmpresaTuristica.query.filter_by(activo=True).order_by(EmpresaTuristica.nombre).all()
    categorias = CategoriaCarta.query.filter_by(activo=True).order_by(CategoriaCarta.orden).all()
    resp = _mkr(render_template('ventas/nueva.html',
        empresas=empresas, categorias=categorias, hoy=now_peru().date(),
        precio_peruhop=PRECIO_PERUHOP, token_inicial=secrets.token_hex(16)))
    # No-cache: evita que el botón Atrás muestre la página en caché con datos viejos
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ──────────────────────────────────────────────────────────────
#  VER VENTA
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/<int:id>')
@login_required
@permiso_required('ventas')
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
    hoy = now_peru().date()
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

        try:
            efectivo      = float(request.form.get('efectivo', 0)      or 0)
            tarjeta       = float(request.form.get('tarjeta', 0)       or 0)
            yape          = float(request.form.get('yape', 0)          or 0)
            transferencia = float(request.form.get('transferencia', 0) or 0)
        except (TypeError, ValueError, OverflowError):
            flash('Ingresa importes válidos para el cierre.', 'error')
            return redirect(url_for('ventas.cierre', fecha=fecha.strftime('%Y-%m-%d')))
        if not all(campo in request.form for campo in ('efectivo', 'tarjeta', 'yape', 'transferencia')):
            flash('Completa los cuatro medios de pago antes de guardar el cierre.', 'error')
            return redirect(url_for('ventas.cierre', fecha=fecha.strftime('%Y-%m-%d')))
        if any(not math.isfinite(v) or v < 0 for v in (efectivo, tarjeta, yape, transferencia)):
            flash('Los importes de cierre deben ser montos válidos y no negativos.', 'error')
            return redirect(url_for('ventas.cierre', fecha=fecha.strftime('%Y-%m-%d')))
        total_cobrado = round(efectivo + tarjeta + yape + transferencia, 2)
        observaciones_cierre = request.form.get('observaciones', '').strip()

        cierre_exist = CierreCaja.query.filter_by(fecha=fecha).first()
        if cierre_exist:
            if not current_user.es_admin():
                flash('Solo administración puede corregir un cierre ya guardado.', 'error')
                return redirect(url_for('ventas.cierre', fecha=fecha.strftime('%Y-%m-%d')))
            if not cierre_exist.abierta and len(observaciones_cierre) < 10:
                flash('Para modificar un cierre ya cerrado, escribe el motivo de la corrección (al menos 10 caracteres).', 'error')
                return redirect(url_for('ventas.cierre', fecha=fecha.strftime('%Y-%m-%d')))
            importe_anterior = cierre_exist.total_cobrado or 0
            accion = 'RECIERRE_CAJA' if cierre_exist.abierta else 'CORREGIR_CIERRE_CAJA'
            detalle = (
                f'Importes anteriores (efectivo/tarjeta/yape/transferencia): '
                f'{cierre_exist.efectivo or 0:.2f}/{cierre_exist.tarjeta or 0:.2f}/'
                f'{cierre_exist.yape or 0:.2f}/{cierre_exist.transferencia or 0:.2f}; '
                f'total anterior: S/.{importe_anterior:.2f}; nuevos importes: '
                f'{efectivo:.2f}/{tarjeta:.2f}/{yape:.2f}/{transferencia:.2f}; nuevo declarado: '
                f'S/.{total_cobrado:.2f}; ventas registradas al cerrar: '
                f'{VentaDiaria.query.filter_by(fecha=fecha).count()}'
            )
            if cierre_exist.abierta:
                detalle += f'; motivo de reapertura: {cierre_exist.motivo_reapertura or "sin dato"}'
            elif observaciones_cierre:
                detalle += f'; motivo de corrección: {observaciones_cierre[:500]}'
            registrar_auditoria(current_user.id, accion, 'cierres_caja', cierre_exist.id,
                                detalle, ip=request.remote_addr)
            cierre_exist.efectivo      = efectivo
            cierre_exist.tarjeta       = tarjeta
            cierre_exist.yape          = yape
            cierre_exist.transferencia = transferencia
            cierre_exist.total_cobrado = total_cobrado
            cierre_exist.observaciones = observaciones_cierre
            cierre_exist.usuario_id    = current_user.id
            cierre_exist.creado_en     = now_peru()
            cierre_exist.abierta       = False
        else:
            c = CierreCaja(
                fecha=fecha,
                efectivo=efectivo, tarjeta=tarjeta,
                yape=yape, transferencia=transferencia,
                total_cobrado=total_cobrado,
                observaciones=observaciones_cierre,
                usuario_id=current_user.id,
                creado_en=now_peru()
            )
            db.session.add(c)
            db.session.flush()
            registrar_auditoria(current_user.id, 'CIERRE_CAJA', 'cierres_caja', c.id,
                                f'Fecha: {fecha}; total declarado: S/.{total_cobrado:.2f}; '
                                f'ventas: {VentaDiaria.query.filter_by(fecha=fecha).count()}',
                                ip=request.remote_addr)

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


@ventas_bp.route('/cierre/<int:cierre_id>/reabrir', methods=['POST'])
@login_required
@admin_required
def reabrir_cierre(cierre_id):
    cierre = CierreCaja.query.filter_by(id=cierre_id).with_for_update().first_or_404()
    motivo = request.form.get('motivo', '').strip()
    if len(motivo) < 10:
        flash('Explica el motivo de la reapertura (al menos 10 caracteres).', 'error')
        return redirect(url_for('ventas.cierre', fecha=cierre.fecha.strftime('%Y-%m-%d')))
    if cierre.abierta:
        flash('Esta caja ya está abierta para correcciones.', 'error')
        return redirect(url_for('ventas.cierre', fecha=cierre.fecha.strftime('%Y-%m-%d')))

    cierre.abierta = True
    cierre.reabierta_en = now_peru()
    cierre.reabierta_por_id = current_user.id
    cierre.motivo_reapertura = motivo[:500]
    registrar_auditoria(
        current_user.id, 'REABRIR_CAJA', 'cierres_caja', cierre.id,
        f'Fecha: {cierre.fecha}; motivo: {motivo[:500]}; '
        f'importe previo: S/.{(cierre.total_cobrado or 0):.2f}; '
        f'ventas existentes: {VentaDiaria.query.filter_by(fecha=cierre.fecha).count()}',
        ip=request.remote_addr,
    )
    db.session.commit()
    flash('Caja reabierta. Registra las ventas pendientes y vuelve a cerrar el día.', 'success')
    return redirect(url_for('ventas.cierre', fecha=cierre.fecha.strftime('%Y-%m-%d')))


# ──────────────────────────────────────────────────────────────
#  PASAJEROS POR DÍA (registro de empresas y rutas)
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
#  EDITAR / ELIMINAR ITEMS DE VENTA (antes del cierre de caja)
# ──────────────────────────────────────────────────────────────
@ventas_bp.route('/item/<int:item_id>/editar', methods=['POST'])
@login_required
@permiso_required('ventas')
def editar_item_venta(item_id):
    item  = ItemVenta.query.get_or_404(item_id)
    venta = item.venta
    # La reapertura administrativa vuelve a habilitar correcciones del día.
    cierre = CierreCaja.query.filter_by(fecha=venta.fecha).first()
    if cierre and not cierre.abierta:
        flash('No se puede editar: la caja de este día ya está cerrada.', 'error')
        return redirect(url_for('ventas.index'))

    try:
        nueva_cant  = float(request.form.get('cantidad', item.cantidad))
        nuevo_precio = float(request.form.get('precio_unit', item.precio_unitario or 0))
    except:
        flash('Datos inválidos.', 'error')
        return redirect(url_for('ventas.index'))

    if nueva_cant <= 0 or nuevo_precio < 0 or not all(map(math.isfinite, (nueva_cant, nuevo_precio))):
        flash('La cantidad debe ser mayor que cero y el precio no puede ser negativo.', 'error')
        return redirect(url_for('ventas.index'))

    cantidad_anterior = float(item.cantidad or 0)
    precio_anterior = float(item.precio_unitario or 0)
    diferencia = nueva_cant - cantidad_anterior
    if diferencia and item.producto_carta_id:
        pc = db.session.get(ProductoCarta, item.producto_carta_id)
        if pc and pc.descuenta_inventario and pc.producto_almacen_id:
            prod = db.session.get(Producto, pc.producto_almacen_id)
            if prod:
                if diferencia > 0 and (prod.stock_actual or 0) < diferencia:
                    flash(f'Stock insuficiente para aumentar la cantidad. Disponible: {prod.stock_actual}.', 'error')
                    return redirect(url_for('ventas.index'))
                tipo_mov = 'egreso' if diferencia > 0 else 'ingreso'
                registrar_ajuste_stock_venta(
                    prod, abs(diferencia), tipo_mov,
                    f'VENTA-{venta.id}-EDICION-ITEM-{item.id}-{int(now_peru().timestamp())}',
                    f'Ajuste por edición de venta #{venta.id} — {item.descripcion}',
                )

    item.cantidad   = nueva_cant
    item.precio_unitario = nuevo_precio
    item.subtotal   = round(nueva_cant * nuevo_precio, 2)

    # Recalcular total de la venta
    venta.total = round(sum(it.subtotal for it in venta.items), 2)
    registrar_auditoria(current_user.id, 'EDITAR_ITEM_VENTA', 'items_venta', item.id,
                        f'Cantidad {cantidad_anterior}→{nueva_cant}; precio {precio_anterior}→{nuevo_precio}',
                        ip=request.remote_addr)
    db.session.commit()
    flash('Item actualizado.', 'success')
    return redirect(url_for('ventas.index'))


@ventas_bp.route('/item/<int:item_id>/eliminar', methods=['POST'])
@login_required
@permiso_required('ventas')
def eliminar_item_venta(item_id):
    item  = ItemVenta.query.get_or_404(item_id)
    venta = item.venta
    cierre = CierreCaja.query.filter_by(fecha=venta.fecha).first()
    if cierre and not cierre.abierta:
        flash('No se puede eliminar: la caja de este día ya está cerrada.', 'error')
        return redirect(url_for('ventas.index'))
    if not current_user.es_admin():
        flash('Solo administración puede eliminar un artículo de una venta.', 'error')
        return redirect(url_for('ventas.index'))

    # Devolver stock si el producto descuenta inventario
    if item.producto_carta_id:
        from models import ProductoCarta, Producto as ProdAlm
        pc = db.session.get(ProductoCarta, item.producto_carta_id)
        if pc and pc.descuenta_inventario and pc.producto_almacen_id:
            prod = db.session.get(ProdAlm, pc.producto_almacen_id)
            if prod:
                registrar_ajuste_stock_venta(
                    prod, float(item.cantidad or 0), 'ingreso',
                    f'VENTA-{venta.id}-ANULACION-ITEM-{item.id}',
                    f'Reversión por eliminar producto de venta #{venta.id} — {item.descripcion}',
                )

    nombre = item.descripcion
    registrar_auditoria(current_user.id, 'ELIMINAR_ITEM_VENTA', 'items_venta', item.id,
                        f'Venta #{venta.id}; artículo: {nombre}', ip=request.remote_addr)
    db.session.delete(item)
    # Recalcular total
    db.session.flush()
    venta.total = round(sum(it.subtotal for it in venta.items), 2)
    db.session.commit()
    flash(f'"{nombre}" eliminado de la venta.', 'success')
    return redirect(url_for('ventas.index'))


@ventas_bp.route('/<int:id>/eliminar-venta', methods=['POST'])
@login_required
@permiso_required('ventas')
def eliminar_venta(id):
    venta  = VentaDiaria.query.get_or_404(id)
    cierre = CierreCaja.query.filter_by(fecha=venta.fecha).first()
    if cierre and not cierre.abierta:
        flash('No se puede eliminar: la caja ya está cerrada.', 'error')
        return redirect(url_for('ventas.index'))
    if not current_user.es_admin():
        flash('Solo administración puede anular una venta.', 'error')
        return redirect(url_for('ventas.index'))
    # Devolver stock de todos los items
    from models import ProductoCarta, Producto as ProdAlm
    for item in venta.items:
        if item.producto_carta_id:
            pc = db.session.get(ProductoCarta, item.producto_carta_id)
            if pc and pc.descuenta_inventario and pc.producto_almacen_id:
                prod = db.session.get(ProdAlm, pc.producto_almacen_id)
                if prod:
                    registrar_ajuste_stock_venta(
                        prod, float(item.cantidad or 0), 'ingreso',
                        f'VENTA-{venta.id}-ANULACION-ITEM-{item.id}',
                        f'Reversión por anular venta #{venta.id} — {item.descripcion}',
                    )
    registrar_auditoria(current_user.id, 'ANULAR_VENTA', 'ventas_diarias', venta.id,
                        f'Total anulado: S/.{venta.total:.2f}', ip=request.remote_addr)
    db.session.delete(venta)
    db.session.commit()
    flash('Venta eliminada y stock revertido.', 'success')
    return redirect(url_for('ventas.index'))

@ventas_bp.route('/pasajeros', methods=['GET', 'POST'])
@login_required
@permiso_required('ventas')
def pasajeros():
    """Registro de pasajeros por empresa y ruta del día"""
    hoy = now_peru().date()
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
@permiso_required('ventas')
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
@permiso_required('ventas')
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
