from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, RegistroPasajeros, EmpresaTuristica, BalonGas, Reserva, VentaDiaria
from datetime import date, datetime, timedelta
import pytz

pasajeros_bp = Blueprint('pasajeros', __name__, url_prefix='/pasajeros')
PERU_TZ = pytz.timezone('America/Lima')

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

def hoy_peru():
    return datetime.now(PERU_TZ).date()

# ─── PASAJEROS ──────────────────────────────────────────────
@pasajeros_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    hoy = hoy_peru()
    fecha_str = request.args.get('fecha', hoy.strftime('%Y-%m-%d'))
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except:
        fecha = hoy

    if request.method == 'POST':
        accion = request.form.get('accion', 'nuevo')

        if accion == 'nuevo':
            empresa_id    = request.form.get('empresa_id') or None
            nombre_grupo  = request.form.get('nombre_grupo', '').strip()
            num_pax       = int(request.form.get('num_pax', 0) or 0)
            precio_buffet = float(request.form.get('precio_buffet', 0) or 0)
            ruta          = request.form.get('ruta', '').strip()
            obs           = request.form.get('observaciones', '').strip()
            fecha_reg     = request.form.get('fecha', hoy.strftime('%Y-%m-%d'))
            try:
                fecha_reg = datetime.strptime(fecha_reg, '%Y-%m-%d').date()
            except:
                fecha_reg = hoy

            reg = RegistroPasajeros(
                fecha=fecha_reg, empresa_id=empresa_id or None,
                nombre_grupo=nombre_grupo, num_pax=num_pax,
                precio_buffet=precio_buffet, ruta=ruta,
                observaciones=obs, usuario_id=current_user.id,
                creado_en=now_peru()
            )
            db.session.add(reg)
            db.session.commit()
            flash(f'Registrado: {num_pax} pax.', 'success')

        elif accion == 'editar':
            reg_id = int(request.form.get('reg_id'))
            reg = RegistroPasajeros.query.get_or_404(reg_id)
            reg.empresa_id    = request.form.get('empresa_id') or None
            reg.nombre_grupo  = request.form.get('nombre_grupo', '').strip()
            reg.num_pax       = int(request.form.get('num_pax', 0) or 0)
            reg.precio_buffet = float(request.form.get('precio_buffet', 0) or 0)
            reg.ruta          = request.form.get('ruta', '').strip()
            reg.observaciones = request.form.get('observaciones', '').strip()
            db.session.commit()
            flash('Registro actualizado.', 'success')

        elif accion == 'eliminar':
            reg = RegistroPasajeros.query.get_or_404(int(request.form.get('reg_id')))
            db.session.delete(reg)
            db.session.commit()
            flash('Registro eliminado.', 'success')

        return redirect(url_for('pasajeros.index', fecha=fecha_str))

    registros = RegistroPasajeros.query.filter_by(fecha=fecha).order_by(RegistroPasajeros.creado_en).all()
    empresas  = EmpresaTuristica.query.filter_by(activo=True).order_by(EmpresaTuristica.nombre).all()

    # Totales por empresa para el resumen
    resumen = {}
    total_pax = 0
    for r in registros:
        key = r.empresa.nombre if r.empresa else (r.nombre_grupo or 'Privado')
        color = r.empresa.color if r.empresa else '#10b981'
        if key not in resumen:
            resumen[key] = {'pax': 0, 'color': color, 'ingresos': 0}
        resumen[key]['pax'] += r.num_pax or 0
        resumen[key]['ingresos'] += (r.num_pax or 0) * (r.precio_buffet or 0)
        total_pax += r.num_pax or 0

    return render_template('pasajeros/index.html',
        registros=registros, empresas=empresas,
        fecha=fecha, hoy=hoy, resumen=resumen, total_pax=total_pax)


# ─── BALONES DE GAS ─────────────────────────────────────────
@pasajeros_bp.route('/gas', methods=['GET', 'POST'])
@login_required
@permiso_required('gas')
def gas():
    if request.method == 'POST':
        accion = request.form.get('accion', 'nuevo')

        if accion == 'nuevo':
            def parse_date(s):
                try: return datetime.strptime(s, '%Y-%m-%d').date()
                except: return None
            b = BalonGas(
                fecha_compra  = parse_date(request.form.get('fecha_compra')) or date.today(),
                fecha_inicio  = parse_date(request.form.get('fecha_inicio')),
                proveedor     = request.form.get('proveedor', '').strip(),
                precio        = float(request.form.get('precio', 0) or 0),
                peso_kg       = float(request.form.get('peso_kg', 10) or 10),
                estado        = request.form.get('estado', 'disponible'),
                observaciones = request.form.get('observaciones', '').strip(),
                usuario_id    = current_user.id,
                creado_en     = now_peru()
            )
            db.session.add(b)
            db.session.commit()
            flash('Balón registrado.', 'success')

        elif accion == 'usar':
            b = BalonGas.query.get_or_404(int(request.form.get('balon_id')))
            b.estado       = 'en_uso'
            b.fecha_inicio = date.today()
            db.session.commit()
            flash('Balón marcado como en uso.', 'success')

        elif accion == 'agotar':
            b = BalonGas.query.get_or_404(int(request.form.get('balon_id')))
            b.estado   = 'agotado'
            b.fecha_fin = date.today()
            if b.fecha_inicio:
                b.dias_uso = (b.fecha_fin - b.fecha_inicio).days or 1
            db.session.commit()
            flash(f'Balón cerrado. Duró {b.dias_uso or "?"} días.', 'success')

        elif accion == 'editar':
            b = BalonGas.query.get_or_404(int(request.form.get('balon_id')))
            b.proveedor     = request.form.get('proveedor', '').strip()
            b.precio        = float(request.form.get('precio', 0) or 0)
            b.peso_kg       = float(request.form.get('peso_kg', 10) or 10)
            b.observaciones = request.form.get('observaciones', '').strip()
            db.session.commit()
            flash('Balón actualizado.', 'success')

        return redirect(url_for('pasajeros.gas'))

    balones = BalonGas.query.order_by(BalonGas.fecha_compra.desc()).all()

    # Estadísticas: promedio de días de duración
    agotados = [b for b in balones if b.estado == 'agotado' and b.dias_uso]
    prom_dias = round(sum(b.dias_uso for b in agotados) / len(agotados), 1) if agotados else None
    en_uso    = [b for b in balones if b.estado == 'en_uso']
    # Proyección: si hay uno en uso, cuántos días le quedan aprox
    dias_transcurridos = None
    dias_restantes_prom = None
    if en_uso and prom_dias and en_uso[0].fecha_inicio:
        dias_transcurridos  = (date.today() - en_uso[0].fecha_inicio).days
        dias_restantes_prom = max(0, round(prom_dias - dias_transcurridos, 1))

    return render_template('pasajeros/gas.html',
        balones=balones, prom_dias=prom_dias, en_uso=en_uso,
        dias_transcurridos=dias_transcurridos,
        dias_restantes_prom=dias_restantes_prom,
        hoy=date.today())


# ─── RESERVAS ───────────────────────────────────────────────
@pasajeros_bp.route('/reservas', methods=['GET', 'POST'])
@login_required
@permiso_required('reservas')
def reservas():
    if request.method == 'POST':
        accion = request.form.get('accion', 'nuevo')

        def parse_date(s):
            try: return datetime.strptime(s, '%Y-%m-%d').date()
            except: return None

        if accion in ('nuevo', 'editar'):
            datos = dict(
                fecha         = parse_date(request.form.get('fecha')),
                hora          = request.form.get('hora', '').strip(),
                nombre_grupo  = request.form.get('nombre_grupo', '').strip(),
                num_pax       = int(request.form.get('num_pax', 0) or 0),
                precio_buffet = float(request.form.get('precio_buffet', 0) or 0),
                empresa_id    = request.form.get('empresa_id') or None,
                observaciones = request.form.get('observaciones', '').strip(),
                estado        = request.form.get('estado', 'pendiente'),  # pendiente|confirmada|cancelada|completada|postergada
            )
            if not datos['fecha']:
                flash('La fecha es obligatoria.', 'error')
                return redirect(url_for('pasajeros.reservas'))

            if accion == 'nuevo':
                r = Reserva(**datos, usuario_id=current_user.id, creado_en=now_peru())
                db.session.add(r)
                flash('Reserva registrada.', 'success')
            else:
                r = Reserva.query.get_or_404(int(request.form.get('reserva_id')))
                for k, v in datos.items():
                    setattr(r, k, v)
                flash('Reserva actualizada.', 'success')

        elif accion == 'cancelar':
            r = Reserva.query.get_or_404(int(request.form.get('reserva_id')))
            r.estado = 'cancelada'
            flash('Reserva cancelada.', 'success')

        elif accion == 'postergar':
            r = Reserva.query.get_or_404(int(request.form.get('reserva_id')))
            r.estado = 'postergada'
            flash('Reserva marcada como postergada.', 'success')

        elif accion == 'completar':
            r = Reserva.query.get_or_404(int(request.form.get('reserva_id')))
            r.estado = 'completada'
            flash('Reserva marcada como completada.', 'success')

        elif accion == 'eliminar':
            r = Reserva.query.get_or_404(int(request.form.get('reserva_id')))
            db.session.delete(r)
            flash('Reserva eliminada.', 'success')

        db.session.commit()
        return redirect(url_for('pasajeros.reservas'))

    hoy = hoy_peru()
    # Alertas: reservas en los próximos 2 días (incluyendo hoy)
    alertas = Reserva.query.filter(
        Reserva.fecha >= hoy,
        Reserva.fecha <= hoy + timedelta(days=2),
        Reserva.estado.in_(['pendiente', 'confirmada', 'postergada'])
    ).order_by(Reserva.fecha, Reserva.hora).all()

    # Reservas próximas (futuras + hoy)
    proximas = Reserva.query.filter(
        Reserva.fecha >= hoy,
        Reserva.estado.in_(['pendiente', 'confirmada', 'postergada'])
    ).order_by(Reserva.fecha, Reserva.hora).all()

    # Historial: pasadas + completadas/canceladas/postergadas futuras
    filtro_hist = request.args.get('hist_estado', '')
    filtro_desde = request.args.get('hist_desde', '')
    filtro_hasta = request.args.get('hist_hasta', '')

    q_hist = Reserva.query.filter(
        (Reserva.fecha < hoy) |
        (Reserva.estado.in_(['completada', 'cancelada']))
    )
    # Excluir futuras pendientes/confirmadas/postergadas (esas van en proximas)
    q_hist = q_hist.filter(
        ~((Reserva.fecha >= hoy) & (Reserva.estado.in_(['pendiente', 'confirmada', 'postergada'])))
    )
    if filtro_hist:
        q_hist = q_hist.filter(Reserva.estado == filtro_hist)
    if filtro_desde:
        try:
            from datetime import datetime as _dt
            q_hist = q_hist.filter(Reserva.fecha >= _dt.strptime(filtro_desde, '%Y-%m-%d').date())
        except: pass
    if filtro_hasta:
        try:
            from datetime import datetime as _dt
            q_hist = q_hist.filter(Reserva.fecha <= _dt.strptime(filtro_hasta, '%Y-%m-%d').date())
        except: pass

    historial = q_hist.order_by(Reserva.fecha.desc()).limit(60).all()

    empresas = EmpresaTuristica.query.filter_by(activo=True).order_by(EmpresaTuristica.nombre).all()

    return render_template('pasajeros/reservas.html',
        alertas=alertas, proximas=proximas, historial=historial,
        empresas=empresas, hoy=hoy,
        filtro_hist=filtro_hist, filtro_desde=filtro_desde, filtro_hasta=filtro_hasta)


# ─── API: alertas de reservas (para el header) ──────────────
@pasajeros_bp.route('/api/alertas')
@login_required
def api_alertas():
    hoy = hoy_peru()
    count = Reserva.query.filter(
        Reserva.fecha >= hoy,
        Reserva.fecha <= hoy + timedelta(days=2),
        Reserva.estado.in_(['pendiente', 'confirmada'])
    ).count()
    return jsonify({'count': count})
