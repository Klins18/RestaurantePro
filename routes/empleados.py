from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Empleado, Asistencia, FuncionDiaria, registrar_auditoria
from datetime import datetime, date, timedelta
import pytz, calendar

empleados_bp = Blueprint('empleados', __name__, url_prefix='/empleados')
PERU_TZ = pytz.timezone('America/Lima')

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

# ─────────────────────────────────
#  LISTA DE EMPLEADOS
# ─────────────────────────────────
@empleados_bp.route('/')
@login_required
def index():
    empleados = Empleado.query.order_by(Empleado.apellidos, Empleado.nombres).all()
    # Cumpleaños próximos (próximos 30 días)
    hoy = date.today()
    cumpleanos_proximos = []
    for e in empleados:
        if e.fecha_nacimiento and e.dias_para_cumpleanos is not None:
            dias = e.dias_para_cumpleanos
            if dias <= 30:
                cumpleanos_proximos.append((e, dias))
    cumpleanos_proximos.sort(key=lambda x: x[1])
    return render_template('empleados/index.html',
                           empleados=empleados,
                           cumpleanos_proximos=cumpleanos_proximos,
                           hoy=hoy)

# ─────────────────────────────────
#  NUEVO EMPLEADO
# ─────────────────────────────────
@empleados_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo():
    if request.method == 'POST':
        fn_str = request.form.get('fecha_nacimiento', '')
        fi_str = request.form.get('fecha_ingreso', '')
        try:
            fn = datetime.strptime(fn_str, '%Y-%m-%d').date() if fn_str else None
        except: fn = None
        try:
            fi = datetime.strptime(fi_str, '%Y-%m-%d').date() if fi_str else None
        except: fi = None

        empleado = Empleado(
            nombres=request.form.get('nombres', '').strip(),
            apellidos=request.form.get('apellidos', '').strip(),
            dni=request.form.get('dni', '').strip() or None,
            telefono=request.form.get('telefono', '').strip(),
            direccion=request.form.get('direccion', '').strip(),
            fecha_nacimiento=fn,
            tipo_sangre=request.form.get('tipo_sangre', '').strip(),
            cargo=request.form.get('cargo', '').strip(),
            fecha_ingreso=fi,
            tipo_contrato=request.form.get('tipo_contrato', 'fijo'),
            sueldo_base=float(request.form.get('sueldo_base', 0) or 0),
            activo=True
        )
        db.session.add(empleado)
        registrar_auditoria(current_user.id, 'NUEVO_EMPLEADO', 'empleados', None,
                            f'{empleado.nombre_completo}', ip=request.remote_addr)
        db.session.commit()
        flash(f'Empleado {empleado.nombre_completo} registrado.', 'success')
        return redirect(url_for('empleados.ver', id=empleado.id))

    return render_template('empleados/nuevo.html', hoy=date.today())

# ─────────────────────────────────
#  VER EMPLEADO
# ─────────────────────────────────
@empleados_bp.route('/<int:id>')
@login_required
def ver(id):
    empleado = Empleado.query.get_or_404(id)
    hoy = date.today()
    # Asistencias del mes actual
    mes_inicio = hoy.replace(day=1)
    asistencias_mes = Asistencia.query.filter(
        Asistencia.empleado_id == id,
        Asistencia.fecha >= mes_inicio,
        Asistencia.fecha <= hoy
    ).order_by(Asistencia.fecha.desc()).all()
    # Funciones de hoy
    funciones_hoy = FuncionDiaria.query.filter_by(
        empleado_id=id, fecha=hoy
    ).order_by(FuncionDiaria.id.desc()).all()
    # Resumen mes
    dias_trabajados = sum(1 for a in asistencias_mes if a.estado == 'presente')
    dias_falta = sum(1 for a in asistencias_mes if a.estado == 'falta')
    dias_libre = sum(1 for a in asistencias_mes if a.estado == 'libre')
    return render_template('empleados/ver.html',
                           empleado=empleado,
                           asistencias_mes=asistencias_mes,
                           funciones_hoy=funciones_hoy,
                           dias_trabajados=dias_trabajados,
                           dias_falta=dias_falta,
                           dias_libre=dias_libre,
                           hoy=hoy)

# ─────────────────────────────────
#  EDITAR EMPLEADO
# ─────────────────────────────────
@empleados_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar(id):
    empleado = Empleado.query.get_or_404(id)
    if request.method == 'POST':
        empleado.nombres    = request.form.get('nombres', '').strip()
        empleado.apellidos  = request.form.get('apellidos', '').strip()
        empleado.dni        = request.form.get('dni', '').strip() or None
        empleado.telefono   = request.form.get('telefono', '').strip()
        empleado.direccion  = request.form.get('direccion', '').strip()
        empleado.tipo_sangre= request.form.get('tipo_sangre', '').strip()
        empleado.cargo      = request.form.get('cargo', '').strip()
        empleado.tipo_contrato = request.form.get('tipo_contrato', 'fijo')
        try:
            empleado.sueldo_base = float(request.form.get('sueldo_base', 0) or 0)
        except: pass
        fn_str = request.form.get('fecha_nacimiento', '')
        fi_str = request.form.get('fecha_ingreso', '')
        try:
            empleado.fecha_nacimiento = datetime.strptime(fn_str, '%Y-%m-%d').date() if fn_str else None
        except: pass
        try:
            empleado.fecha_ingreso = datetime.strptime(fi_str, '%Y-%m-%d').date() if fi_str else None
        except: pass
        empleado.activo = request.form.get('activo') == 'on'
        db.session.commit()
        flash('Datos actualizados.', 'success')
        return redirect(url_for('empleados.ver', id=id))
    return render_template('empleados/editar.html', empleado=empleado)

# ─────────────────────────────────
#  REGISTRAR ASISTENCIA (un día, todos)
# ─────────────────────────────────
@empleados_bp.route('/asistencia', methods=['GET', 'POST'])
@login_required
def asistencia():
    hoy = date.today()
    fecha_str = request.args.get('fecha', hoy.strftime('%Y-%m-%d'))
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except:
        fecha = hoy

    empleados = Empleado.query.filter_by(activo=True).order_by(Empleado.apellidos).all()

    # Cargar asistencias ya registradas para esa fecha
    asist_map = {}
    for a in Asistencia.query.filter_by(fecha=fecha).all():
        asist_map[a.empleado_id] = a

    if request.method == 'POST':
        fecha_post_str = request.form.get('fecha', hoy.strftime('%Y-%m-%d'))
        try:
            fecha_post = datetime.strptime(fecha_post_str, '%Y-%m-%d').date()
        except:
            fecha_post = hoy

        for emp in empleados:
            estado = request.form.get(f'estado_{emp.id}', 'presente')
            hora_e = request.form.get(f'hora_entrada_{emp.id}', '')
            hora_s = request.form.get(f'hora_salida_{emp.id}', '')
            obs    = request.form.get(f'obs_{emp.id}', '')
            try:
                horas_e = float(request.form.get(f'horas_extra_{emp.id}', 0) or 0)
            except: horas_e = 0
            try:
                desc = float(request.form.get(f'descuento_{emp.id}', 0) or 0)
            except: desc = 0

            asist = asist_map.get(emp.id)
            if asist:
                asist.estado = estado
                asist.hora_entrada = hora_e
                asist.hora_salida  = hora_s
                asist.horas_extra  = horas_e
                asist.descuento    = desc
                asist.observacion  = obs
                asist.registrado_por = current_user.id
            else:
                asist = Asistencia(
                    empleado_id=emp.id, fecha=fecha_post,
                    estado=estado, hora_entrada=hora_e, hora_salida=hora_s,
                    horas_extra=horas_e, descuento=desc, observacion=obs,
                    registrado_por=current_user.id, creado_en=now_peru()
                )
                db.session.add(asist)

        registrar_auditoria(current_user.id, 'ASISTENCIA', 'asistencias', None,
                            f'Fecha: {fecha_post_str}', ip=request.remote_addr)
        db.session.commit()
        flash(f'Asistencia del {fecha_post.strftime("%d/%m/%Y")} guardada.', 'success')
        return redirect(url_for('empleados.asistencia', fecha=fecha_post_str))

    return render_template('empleados/asistencia.html',
                           empleados=empleados, fecha=fecha,
                           asist_map=asist_map, hoy=hoy)

# ─────────────────────────────────
#  REPORTE DE ASISTENCIA MENSUAL
# ─────────────────────────────────
@empleados_bp.route('/reporte')
@login_required
def reporte():
    hoy = date.today()
    mes  = int(request.args.get('mes',  hoy.month))
    anio = int(request.args.get('anio', hoy.year))

    # Rango del mes
    _, dias_mes = calendar.monthrange(anio, mes)
    inicio = date(anio, mes, 1)
    fin    = date(anio, mes, dias_mes)
    dias   = [date(anio, mes, d) for d in range(1, dias_mes + 1)]

    empleados = Empleado.query.filter_by(activo=True).order_by(Empleado.apellidos).all()

    # Cargar todas las asistencias del mes de una sola consulta
    asistencias = Asistencia.query.filter(
        Asistencia.fecha >= inicio,
        Asistencia.fecha <= fin
    ).all()
    # Mapa {(empleado_id, fecha): Asistencia}
    asist_map = {(a.empleado_id, a.fecha): a for a in asistencias}

    return render_template('empleados/reporte.html',
                           empleados=empleados, dias=dias,
                           asist_map=asist_map,
                           mes=mes, anio=anio,
                           nombre_mes=calendar.month_name[mes])

# ─────────────────────────────────
#  FUNCIONES DIARIAS
# ─────────────────────────────────
@empleados_bp.route('/funciones', methods=['GET', 'POST'])
@login_required
def funciones():
    hoy = date.today()
    fecha_str = request.args.get('fecha', hoy.strftime('%Y-%m-%d'))
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except:
        fecha = hoy

    if request.method == 'POST':
        empleado_id = request.form.get('empleado_id')
        funcion     = request.form.get('funcion', '').strip()
        area        = request.form.get('area', '')
        obs         = request.form.get('observacion', '')
        fecha_f_str = request.form.get('fecha', hoy.strftime('%Y-%m-%d'))
        try:
            fecha_f = datetime.strptime(fecha_f_str, '%Y-%m-%d').date()
        except:
            fecha_f = hoy

        if empleado_id and funcion:
            f = FuncionDiaria(
                empleado_id=int(empleado_id),
                fecha=fecha_f,
                funcion=funcion,
                area=area,
                observacion=obs,
                registrado_por=current_user.id,
                creado_en=now_peru()
            )
            db.session.add(f)
            db.session.commit()
            flash('Función registrada.', 'success')
        return redirect(url_for('empleados.funciones', fecha=fecha_f_str))

    empleados = Empleado.query.filter_by(activo=True).order_by(Empleado.apellidos).all()
    funciones_dia = FuncionDiaria.query.filter_by(fecha=fecha)\
        .order_by(FuncionDiaria.empleado_id, FuncionDiaria.id).all()

    return render_template('empleados/funciones.html',
                           empleados=empleados,
                           funciones_dia=funciones_dia,
                           fecha=fecha, hoy=hoy)

# ─────────────────────────────────
#  TOGGLE FUNCIÓN COMPLETADA
# ─────────────────────────────────
@empleados_bp.route('/funciones/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_funcion(id):
    f = FuncionDiaria.query.get_or_404(id)
    f.completado = not f.completado
    db.session.commit()
    return jsonify({'completado': f.completado})

# ─────────────────────────────────
#  ELIMINAR FUNCIÓN
# ─────────────────────────────────
@empleados_bp.route('/funciones/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_funcion(id):
    f = FuncionDiaria.query.get_or_404(id)
    db.session.delete(f)
    db.session.commit()
    return redirect(request.referrer or url_for('empleados.funciones'))
