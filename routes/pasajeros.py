from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
import os
import uuid
import math
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user
from routes.decorators import permiso_required
from models import db, RegistroPasajeros, EmpresaTuristica, Reserva, VentaDiaria
from datetime import date, datetime, timedelta
import pytz

pasajeros_bp = Blueprint('pasajeros', __name__, url_prefix='/pasajeros')
PERU_TZ = pytz.timezone('America/Lima')

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

UPLOAD_RESERVAS = 'static/uploads/reservas'
ALLOWED_EXT = {'pdf','png','jpg','jpeg','webp'}

def guardar_voucher_reserva(file):
    if file and file.filename and '.' in file.filename:
        ext = file.filename.rsplit('.',1)[1].lower()
        if ext in ALLOWED_EXT:
            from flask import current_app
            folder = os.path.join(current_app.instance_path, 'uploads', 'reservas')
            os.makedirs(folder, exist_ok=True)
            fname = f'{uuid.uuid4().hex}.{ext}'
            file.save(os.path.join(folder, fname))
            return fname
    return None

def hoy_peru():
    return datetime.now(PERU_TZ).date()

# ─── PASAJEROS ──────────────────────────────────────────────
@pasajeros_bp.route('/', methods=['GET', 'POST'])
@login_required
@permiso_required('reservas')
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
            try:
                num_pax = int(request.form.get('num_pax', 0) or 0)
                precio_buffet = float(request.form.get('precio_buffet', 0) or 0)
                if num_pax < 1 or precio_buffet < 0 or not math.isfinite(precio_buffet):
                    raise ValueError
                if empresa_id and not db.session.get(EmpresaTuristica, empresa_id):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                flash('Pasajeros, precio o empresa inválidos.', 'error')
                return redirect(url_for('pasajeros.index', fecha=fecha_str))
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
            try:
                reg_id = int(request.form.get('reg_id'))
                num_pax = int(request.form.get('num_pax', 0) or 0)
                precio_buffet = float(request.form.get('precio_buffet', 0) or 0)
                empresa_id = request.form.get('empresa_id') or None
                if num_pax < 1 or precio_buffet < 0 or not math.isfinite(precio_buffet):
                    raise ValueError
                if empresa_id and not db.session.get(EmpresaTuristica, empresa_id):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                flash('Pasajeros, precio o empresa inválidos.', 'error')
                return redirect(url_for('pasajeros.index', fecha=fecha_str))
            reg = RegistroPasajeros.query.get_or_404(reg_id)
            reg.empresa_id    = empresa_id
            reg.nombre_grupo  = request.form.get('nombre_grupo', '').strip()
            reg.num_pax       = num_pax
            reg.precio_buffet = precio_buffet
            reg.ruta          = request.form.get('ruta', '').strip()
            reg.observaciones = request.form.get('observaciones', '').strip()
            db.session.commit()
            flash('Registro actualizado.', 'success')

        elif accion == 'eliminar':
            reg = RegistroPasajeros.query.get_or_404(int(request.form.get('reg_id')))
            db.session.delete(reg)
            db.session.commit()
            flash('Registro eliminado.', 'success')
        else:
            flash('Acción de pasajeros inválida.', 'error')

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
            resumen[key] = {'pax': 0, 'color': color}
        resumen[key]['pax'] += r.num_pax or 0
        total_pax += r.num_pax or 0

    return render_template('pasajeros/index.html',
        registros=registros, empresas=empresas,
        fecha=fecha, hoy=hoy, resumen=resumen, total_pax=total_pax)


# Compatibilidad con enlaces guardados anteriores.
@pasajeros_bp.route('/gas', methods=['GET', 'POST'])
@login_required
@permiso_required('gas')
def gas_legacy():
    return redirect(url_for('operaciones.gas'), code=307 if request.method == 'POST' else 301)


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
            try:
                num_pax = int(request.form.get('num_pax', 0) or 0)
                precio_buffet = float(request.form.get('precio_buffet', 0) or 0)
                estado = request.form.get('estado', 'pendiente')
                if num_pax < 0 or precio_buffet < 0 or not math.isfinite(precio_buffet):
                    raise ValueError
                if estado not in {'pendiente', 'confirmada', 'cancelada', 'completada', 'postergada'}:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                flash('Pasajeros, precio o estado inválidos.', 'error')
                return redirect(url_for('pasajeros.reservas'))
            datos = dict(
                fecha         = parse_date(request.form.get('fecha')),
                hora          = request.form.get('hora', '').strip(),
                nombre_grupo  = request.form.get('nombre_grupo', '').strip(),
                num_pax       = num_pax,
                precio_buffet = precio_buffet,
                empresa_id    = request.form.get('empresa_id') or None,
                empresa_libre = request.form.get('empresa_libre', '').strip(),
                numero_file   = request.form.get('numero_file', '').strip(),
                observaciones = request.form.get('observaciones', '').strip(),
                estado        = estado,
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

        elif accion == 'pago':
            r = Reserva.query.get_or_404(int(request.form.get('reserva_id')))
            try:
                monto_ant = float(request.form.get('monto_anticipado', 0) or 0)
                if monto_ant < 0 or not math.isfinite(monto_ant):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                flash('El adelanto debe ser un monto válido y no negativo.', 'error')
                return redirect(url_for('pasajeros.reservas'))
            total_esp = round((r.num_pax or 0) * (r.precio_buffet or 0), 2)
            if monto_ant > total_esp:
                flash('El adelanto supera el total de la reserva. Revisa el monto.', 'error')
                return redirect(url_for('pasajeros.reservas'))
            saldo = round(total_esp - monto_ant, 2)
            archivo = guardar_voucher_reserva(request.files.get('archivo_voucher'))
            r.monto_anticipado = monto_ant
            r.saldo_pendiente  = max(0, saldo)
            r.tipo_pago        = request.form.get('tipo_pago', '')
            r.estado_pago      = 'pagado' if saldo <= 0 else ('anticipado' if monto_ant > 0 else 'sin_pago')
            if archivo:
                r.archivo_voucher = archivo
            flash(f'Pago registrado: S/.{monto_ant:.2f} anticipado, saldo S/.{max(0,saldo):.2f}', 'success')

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
            if not current_user.es_admin():
                flash('Solo administración puede eliminar reservas. Puedes cancelarlas para conservar el historial.', 'error')
                return redirect(url_for('pasajeros.reservas'))
            r = Reserva.query.get_or_404(int(request.form.get('reserva_id')))
            db.session.delete(r)
            flash('Reserva eliminada.', 'success')

        else:
            flash('Acción de reserva inválida.', 'error')
            return redirect(url_for('pasajeros.reservas'))

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
@pasajeros_bp.route('/reservas/voucher/<filename>')
@login_required
@permiso_required('reservas')
def reserva_voucher(filename):
    from flask import current_app
    safe_name = secure_filename(filename)
    private_folder = os.path.join(current_app.instance_path, 'uploads', 'reservas')
    legacy_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'reservas')
    folder = private_folder if os.path.isfile(os.path.join(private_folder, safe_name)) else legacy_folder
    return send_from_directory(folder, safe_name, as_attachment=True)


@pasajeros_bp.route('/api/alertas')
@login_required
@permiso_required('reservas')
def api_alertas():
    hoy = hoy_peru()
    count = Reserva.query.filter(
        Reserva.fecha >= hoy,
        Reserva.fecha <= hoy + timedelta(days=2),
        Reserva.estado.in_(['pendiente', 'confirmada'])
    ).count()
    return jsonify({'count': count})
