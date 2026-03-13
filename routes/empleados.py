import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from routes.decorators import admin_required, supervisor_required, permiso_required
from werkzeug.utils import secure_filename
from models import (db, Empleado, Asistencia, FuncionDiaria, Usuario,
                    AuditoriaAsistencia, CierreAsistencia, Honorario, registrar_auditoria)
from datetime import date, datetime, timedelta
import pytz

empleados_bp = Blueprint('empleados', __name__, url_prefix='/empleados')
PERU_TZ = pytz.timezone('America/Lima')

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

UPLOAD_HONORARIOS = os.path.join('static', 'uploads', 'honorarios')

def guardar_archivo_honorario(file):
    if not file or file.filename == '':
        return None
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in ['.pdf', '.jpg', '.jpeg', '.png']:
        return None
    nombre = f"honorario_{uuid.uuid4().hex[:10]}{ext}"
    os.makedirs(UPLOAD_HONORARIOS, exist_ok=True)
    file.save(os.path.join(UPLOAD_HONORARIOS, nombre))
    return nombre

# ─────────────────────────────────
#  LISTADO
# ─────────────────────────────────
@empleados_bp.route('/')
@login_required
def index():
    empleados = Empleado.query.order_by(Empleado.apellidos).all()
    # Usuarios sin empleado vinculado (para mostrar en formulario)
    usuarios_libres = Usuario.query.filter(
        ~Usuario.id.in_([e.usuario_id for e in empleados if e.usuario_id])
    ).all()
    return render_template('empleados/index.html',
                           empleados=empleados, usuarios_libres=usuarios_libres,
                           hoy=date.today())

# ─────────────────────────────────
#  NUEVO EMPLEADO
# ─────────────────────────────────
@empleados_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo():
    if request.method == 'POST':
        fn_str = request.form.get('fecha_nacimiento', '')
        fi_str = request.form.get('fecha_ingreso', '')
        try: fn = datetime.strptime(fn_str, '%Y-%m-%d').date() if fn_str else None
        except: fn = None
        try: fi = datetime.strptime(fi_str, '%Y-%m-%d').date() if fi_str else None
        except: fi = None

        empleado = Empleado(
            nombres=request.form.get('nombres', '').strip(),
            apellidos=request.form.get('apellidos', '').strip(),
            dni=request.form.get('dni', '').strip() or None,
            telefono=request.form.get('telefono', '').strip(),
            direccion=request.form.get('direccion', '').strip(),
            fecha_nacimiento=fn, tipo_sangre=request.form.get('tipo_sangre', '').strip(),
            cargo=request.form.get('cargo', '').strip(),
            fecha_ingreso=fi,
            tipo_contrato=request.form.get('tipo_contrato', 'fijo'),
            sueldo_base=float(request.form.get('sueldo_base', 0) or 0),
            activo=True
        )

        # Crear cuenta de usuario vinculada
        crear_cuenta = request.form.get('crear_cuenta') == '1'
        if crear_cuenta:
            username = request.form.get('nuevo_username', '').strip()
            password = request.form.get('nuevo_password', '').strip()
            if username and password:
                if Usuario.query.filter_by(username=username).first():
                    flash(f'El usuario "{username}" ya existe.', 'error')
                    return render_template('empleados/nuevo.html', hoy=date.today())
                rol = request.form.get('nuevo_rol', 'empleado')
                u = Usuario(username=username, nombre_completo=empleado.nombres + ' ' + request.form.get('apellidos','').strip(),
                            rol=rol, password_hash=generate_password_hash(password), activo=True)
                db.session.add(u)
                db.session.flush()
                empleado.usuario_id = u.id

        db.session.add(empleado)
        registrar_auditoria(current_user.id, 'NUEVO_EMPLEADO', 'empleados', None,
                            f'{empleado.nombres} {empleado.apellidos}', ip=request.remote_addr)
        db.session.commit()
        flash(f'Empleado registrado correctamente.', 'success')
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
    asistencias_mes = Asistencia.query.filter(
        Asistencia.empleado_id == id,
        Asistencia.fecha >= hoy.replace(day=1)
    ).order_by(Asistencia.fecha.desc()).all()
    honorarios = Honorario.query.filter_by(empleado_id=id).order_by(Honorario.fecha_pago.desc()).limit(10).all()
    usuarios_disponibles = Usuario.query.filter(
        (Usuario.id == empleado.usuario_id) |
        (~Usuario.id.in_([e.usuario_id for e in Empleado.query.filter(Empleado.id != id, Empleado.usuario_id.isnot(None)).all()]))
    ).all()
    return render_template('empleados/ver.html',
                           empleado=empleado, asistencias_mes=asistencias_mes,
                           honorarios=honorarios, hoy=hoy,
                           usuarios_disponibles=usuarios_disponibles)

# ─────────────────────────────────
#  EDITAR EMPLEADO
# ─────────────────────────────────
@empleados_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    empleado = Empleado.query.get_or_404(id)
    if request.method == 'POST':
        fn_str = request.form.get('fecha_nacimiento', '')
        fi_str = request.form.get('fecha_ingreso', '')
        try: fn = datetime.strptime(fn_str, '%Y-%m-%d').date() if fn_str else None
        except: fn = None
        try: fi = datetime.strptime(fi_str, '%Y-%m-%d').date() if fi_str else None
        except: fi = None

        empleado.nombres = request.form.get('nombres', '').strip()
        empleado.apellidos = request.form.get('apellidos', '').strip()
        empleado.dni = request.form.get('dni', '').strip() or None
        empleado.telefono = request.form.get('telefono', '').strip()
        empleado.direccion = request.form.get('direccion', '').strip()
        empleado.fecha_nacimiento = fn
        empleado.tipo_sangre = request.form.get('tipo_sangre', '').strip()
        empleado.cargo = request.form.get('cargo', '').strip()
        empleado.fecha_ingreso = fi
        empleado.tipo_contrato = request.form.get('tipo_contrato', 'fijo')
        empleado.sueldo_base = float(request.form.get('sueldo_base', 0) or 0)
        empleado.activo = request.form.get('activo') == '1'

        # Vincular usuario existente
        vincular_uid = request.form.get('vincular_usuario_id', '').strip()
        if vincular_uid:
            empleado.usuario_id = int(vincular_uid) if vincular_uid != '0' else None

        db.session.commit()
        flash('Empleado actualizado.', 'success')
        return redirect(url_for('empleados.ver', id=id))

    usuarios_disponibles = Usuario.query.all()
    return render_template('empleados/editar.html',
                           empleado=empleado, usuarios_disponibles=usuarios_disponibles)

# ─────────────────────────────────
#  VINCULAR / CREAR CUENTA USUARIO
# ─────────────────────────────────
@empleados_bp.route('/<int:id>/vincular-usuario', methods=['POST'])
@login_required
@admin_required
def vincular_usuario(id):
    empleado = Empleado.query.get_or_404(id)
    accion = request.form.get('accion', 'vincular')

    if accion == 'vincular':
        uid = request.form.get('usuario_id', '').strip()
        empleado.usuario_id = int(uid) if uid else None
        db.session.commit()
        flash('Usuario vinculado correctamente.', 'success')

    elif accion == 'crear':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        rol      = request.form.get('rol', 'empleado')
        if not username or not password:
            flash('Usuario y contraseña son obligatorios.', 'error')
            return redirect(url_for('empleados.ver', id=id))
        if Usuario.query.filter_by(username=username).first():
            flash(f'El usuario "{username}" ya existe.', 'error')
            return redirect(url_for('empleados.ver', id=id))
        u = Usuario(username=username, nombre_completo=empleado.nombre_completo,
                    rol=rol, password_hash=generate_password_hash(password), activo=True)
        db.session.add(u)
        db.session.flush()
        empleado.usuario_id = u.id
        db.session.commit()
        flash(f'Cuenta "{username}" creada y vinculada.', 'success')

    elif accion == 'desvincular':
        empleado.usuario_id = None
        db.session.commit()
        flash('Usuario desvinculado.', 'success')

    return redirect(url_for('empleados.ver', id=id))

# ─────────────────────────────────
#  CAMBIAR CONTRASEÑA (admin → empleado)
# ─────────────────────────────────
@empleados_bp.route('/<int:id>/cambiar-password', methods=['POST'])
@login_required
@admin_required
def cambiar_password(id):
    empleado = Empleado.query.get_or_404(id)
    if not empleado.usuario:
        flash('Este empleado no tiene cuenta vinculada.', 'error')
        return redirect(url_for('empleados.ver', id=id))

    nueva = request.form.get('nueva_password', '').strip()
    if len(nueva) < 3:
        flash('La contraseña debe tener al menos 3 caracteres.', 'error')
        return redirect(url_for('empleados.ver', id=id))

    empleado.usuario.password_hash = generate_password_hash(nueva)
    registrar_auditoria(current_user.id, 'CAMBIO_PASSWORD', 'usuarios', empleado.usuario.id,
                        f'Admin cambió contraseña de {empleado.nombre_completo}', ip=request.remote_addr)
    db.session.commit()
    flash(f'Contraseña de {empleado.usuario.username} actualizada.', 'success')
    return redirect(url_for('empleados.ver', id=id))

# ─────────────────────────────────
#  CAMBIAR MI PROPIA CONTRASEÑA
# ─────────────────────────────────
@empleados_bp.route('/mi-password', methods=['GET', 'POST'])
@login_required
def mi_password():
    if request.method == 'POST':
        actual  = request.form.get('password_actual', '')
        nueva   = request.form.get('nueva_password', '').strip()
        repite  = request.form.get('repite_password', '').strip()

        from werkzeug.security import check_password_hash
        if not check_password_hash(current_user.password_hash, actual):
            flash('La contraseña actual es incorrecta.', 'error')
            return redirect(url_for('empleados.mi_password'))
        if nueva != repite:
            flash('Las contraseñas nuevas no coinciden.', 'error')
            return redirect(url_for('empleados.mi_password'))
        if len(nueva) < 3:
            flash('La contraseña debe tener al menos 3 caracteres.', 'error')
            return redirect(url_for('empleados.mi_password'))

        current_user.password_hash = generate_password_hash(nueva)
        db.session.commit()
        flash('Contraseña cambiada exitosamente.', 'success')
        return redirect(url_for('main.dashboard'))

    return render_template('empleados/mi_password.html')

# ─────────────────────────────────
#  ASISTENCIA  (con cierre y auditoría)
# ─────────────────────────────────
@empleados_bp.route('/asistencia', methods=['GET', 'POST'])
@login_required
@permiso_required('asistencia')
def asistencia():
    hoy = date.today()
    fecha_str = request.args.get('fecha', hoy.strftime('%Y-%m-%d'))
    try: fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except: fecha = hoy

    empleados_activos = Empleado.query.filter_by(activo=True).order_by(Empleado.apellidos).all()
    asist_map = {a.empleado_id: a for a in Asistencia.query.filter_by(fecha=fecha).all()}
    cierre = CierreAsistencia.query.filter_by(fecha=fecha).first()

    if request.method == 'POST':
        accion = request.form.get('accion', 'guardar')

        if accion == 'cerrar':
            if cierre:
                flash('La asistencia de este día ya está cerrada.', 'error')
            else:
                cierre = CierreAsistencia(fecha=fecha, cerrado_por=current_user.id, cerrado_en=now_peru())
                db.session.add(cierre)
                db.session.commit()
                flash(f'Asistencia del {fecha.strftime("%d/%m/%Y")} cerrada.', 'success')
            return redirect(url_for('empleados.asistencia', fecha=fecha_str))

        if accion == 'editar_manual':
            # Edición manual post-cierre con justificación
            asist_id   = int(request.form.get('asist_id'))
            campo      = request.form.get('campo')
            valor_nuevo = request.form.get('valor_nuevo', '').strip()
            justif     = request.form.get('justificacion', '').strip()
            if not justif:
                flash('Se requiere justificación para editar manualmente.', 'error')
                return redirect(url_for('empleados.asistencia', fecha=fecha_str))
            asist = Asistencia.query.get_or_404(asist_id)
            valor_anterior = str(getattr(asist, campo, ''))
            setattr(asist, campo, valor_nuevo)
            db.session.add(AuditoriaAsistencia(
                asistencia_id=asist_id, empleado_id=asist.empleado_id,
                campo_cambiado=campo, valor_anterior=valor_anterior,
                valor_nuevo=valor_nuevo, justificacion=justif,
                usuario_id=current_user.id, fecha_hora=now_peru()
            ))
            db.session.commit()
            flash('Asistencia editada. Cambio registrado en auditoría.', 'success')
            return redirect(url_for('empleados.asistencia', fecha=fecha_str))

        # Guardar asistencia normal (solo si no está cerrada)
        if cierre:
            flash('No se puede modificar: la asistencia de este día ya está cerrada.', 'error')
            return redirect(url_for('empleados.asistencia', fecha=fecha_str))

        fecha_post_str = request.form.get('fecha', hoy.strftime('%Y-%m-%d'))
        try: fecha_post = datetime.strptime(fecha_post_str, '%Y-%m-%d').date()
        except: fecha_post = hoy

        for emp in empleados_activos:
            estado = request.form.get(f'estado_{emp.id}', 'presente')
            hora_e = request.form.get(f'hora_entrada_{emp.id}', '')
            hora_s = request.form.get(f'hora_salida_{emp.id}', '')
            obs    = request.form.get(f'obs_{emp.id}', '')
            try: horas_e = float(request.form.get(f'horas_extra_{emp.id}', 0) or 0)
            except: horas_e = 0
            try: desc = float(request.form.get(f'descuento_{emp.id}', 0) or 0)
            except: desc = 0

            asist = asist_map.get(emp.id)
            if asist:
                asist.estado = estado; asist.hora_entrada = hora_e
                asist.hora_salida = hora_s; asist.horas_extra = horas_e
                asist.descuento = desc; asist.observacion = obs
                asist.registrado_por = current_user.id
            else:
                db.session.add(Asistencia(
                    empleado_id=emp.id, fecha=fecha_post, estado=estado,
                    hora_entrada=hora_e, hora_salida=hora_s, horas_extra=horas_e,
                    descuento=desc, observacion=obs,
                    registrado_por=current_user.id, creado_en=now_peru()
                ))

        registrar_auditoria(current_user.id, 'ASISTENCIA', 'asistencias', None,
                            f'Fecha: {fecha_post_str}', ip=request.remote_addr)
        db.session.commit()
        flash(f'Asistencia del {fecha_post.strftime("%d/%m/%Y")} guardada.', 'success')
        return redirect(url_for('empleados.asistencia', fecha=fecha_post_str))

    # Historial de auditoría de la fecha
    auditoria_dia = AuditoriaAsistencia.query.join(Asistencia).filter(
        Asistencia.fecha == fecha
    ).order_by(AuditoriaAsistencia.fecha_hora.desc()).all()

    return render_template('empleados/asistencia.html',
                           empleados=empleados_activos, fecha=fecha,
                           asist_map=asist_map, hoy=hoy,
                           cierre=cierre, auditoria_dia=auditoria_dia)

# ─────────────────────────────────
#  REPORTE MENSUAL
# ─────────────────────────────────
@empleados_bp.route('/reporte')
@login_required
@permiso_required('asistencia')
def reporte():
    hoy  = date.today()
    mes  = int(request.args.get('mes', hoy.month))
    anio = int(request.args.get('anio', hoy.year))
    desde = date(anio, mes, 1)
    if mes == 12:
        hasta = date(anio + 1, 1, 1) - timedelta(days=1)
    else:
        hasta = date(anio, mes + 1, 1) - timedelta(days=1)

    empleados_activos = Empleado.query.filter_by(activo=True).order_by(Empleado.apellidos).all()
    asistencias = Asistencia.query.filter(
        Asistencia.fecha >= desde, Asistencia.fecha <= hasta
    ).all()

    resumen = {}
    for emp in empleados_activos:
        asist_emp = [a for a in asistencias if a.empleado_id == emp.id]
        resumen[emp.id] = {
            'empleado': emp,
            'presente': sum(1 for a in asist_emp if a.estado == 'presente'),
            'falta':    sum(1 for a in asist_emp if a.estado == 'falta'),
            'tardanza': sum(1 for a in asist_emp if a.estado == 'tardanza'),
            'libre':    sum(1 for a in asist_emp if a.estado == 'libre'),
            'horas_extra': sum(a.horas_extra or 0 for a in asist_emp),
            'descuentos':  sum(a.descuento or 0 for a in asist_emp),
        }

    return render_template('empleados/reporte.html',
                           resumen=resumen, mes=mes, anio=anio,
                           desde=desde, hasta=hasta, hoy=hoy)

# ─────────────────────────────────
#  FUNCIONES DIARIAS
# ─────────────────────────────────
@empleados_bp.route('/funciones', methods=['GET', 'POST'])
@login_required
def funciones():
    hoy = date.today()
    fecha_str = request.args.get('fecha', hoy.strftime('%Y-%m-%d'))
    try: fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except: fecha = hoy

    empleados_activos = Empleado.query.filter_by(activo=True).order_by(Empleado.apellidos).all()

    if request.method == 'POST':
        emp_id  = int(request.form.get('empleado_id'))
        funcion = request.form.get('funcion', '').strip()
        area    = request.form.get('area', '').strip()
        fecha_f_str = request.form.get('fecha', hoy.strftime('%Y-%m-%d'))
        try: fecha_f = datetime.strptime(fecha_f_str, '%Y-%m-%d').date()
        except: fecha_f = hoy

        if funcion:
            db.session.add(FuncionDiaria(
                empleado_id=emp_id, fecha=fecha_f, funcion=funcion,
                area=area, registrado_por=current_user.id, creado_en=now_peru()
            ))
            db.session.commit()
            flash('Función registrada.', 'success')
        return redirect(url_for('empleados.funciones', fecha=fecha_f_str))

    funciones_dia = FuncionDiaria.query.filter_by(fecha=fecha).order_by(FuncionDiaria.empleado_id).all()
    return render_template('empleados/funciones.html',
                           empleados=empleados_activos, funciones=funciones_dia,
                           fecha=fecha, hoy=hoy)

@empleados_bp.route('/funciones/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_funcion(id):
    f = FuncionDiaria.query.get_or_404(id)
    f.completado = not f.completado
    db.session.commit()
    return jsonify({'ok': True, 'completado': f.completado})

@empleados_bp.route('/funciones/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_funcion(id):
    f = FuncionDiaria.query.get_or_404(id)
    db.session.delete(f)
    db.session.commit()
    flash('Función eliminada.', 'success')
    return redirect(request.referrer or url_for('empleados.funciones'))

# ─────────────────────────────────
#  HONORARIOS
# ─────────────────────────────────
@empleados_bp.route('/honorarios')
@login_required
@permiso_required('honorarios')
def honorarios():
    desde_str = request.args.get('desde', '')
    hasta_str = request.args.get('hasta', '')
    emp_id    = request.args.get('empleado_id', '')
    hoy = date.today()
    desde = datetime.strptime(desde_str, '%Y-%m-%d').date() if desde_str else date(hoy.year, hoy.month, 1)
    hasta = datetime.strptime(hasta_str, '%Y-%m-%d').date() if hasta_str else hoy

    q = Honorario.query.filter(Honorario.fecha_pago >= desde, Honorario.fecha_pago <= hasta)
    if emp_id:
        q = q.filter(Honorario.empleado_id == int(emp_id))
    honorarios = q.order_by(Honorario.fecha_pago.desc()).all()
    empleados_activos = Empleado.query.filter_by(activo=True).order_by(Empleado.apellidos).all()
    total = sum(h.monto for h in honorarios)

    return render_template('empleados/honorarios.html',
                           honorarios=honorarios, empleados=empleados_activos,
                           desde=desde, hasta=hasta, total=total,
                           emp_id=emp_id, hoy=hoy)

@empleados_bp.route('/honorarios/nuevo', methods=['POST'])
@login_required
@permiso_required('honorarios')
def nuevo_honorario():
    def pd(s):
        try: return datetime.strptime(s, '%Y-%m-%d').date()
        except: return None

    archivo = guardar_archivo_honorario(request.files.get('archivo_recibo'))
    h = Honorario(
        empleado_id   = int(request.form.get('empleado_id')),
        fecha_pago    = pd(request.form.get('fecha_pago')) or date.today(),
        periodo_desde = pd(request.form.get('periodo_desde')),
        periodo_hasta = pd(request.form.get('periodo_hasta')),
        monto         = float(request.form.get('monto', 0) or 0),
        tipo_pago     = request.form.get('tipo_pago', 'efectivo'),
        concepto      = request.form.get('concepto', '').strip(),
        numero_recibo = request.form.get('numero_recibo', '').strip(),
        archivo_recibo = archivo,
        observaciones = request.form.get('observaciones', '').strip(),
        usuario_id    = current_user.id,
        creado_en     = now_peru()
    )
    db.session.add(h)
    db.session.commit()
    flash('Honorario registrado.', 'success')
    return redirect(url_for('empleados.honorarios'))

@empleados_bp.route('/honorarios/<int:id>/eliminar', methods=['POST'])
@login_required
@permiso_required('honorarios')
def eliminar_honorario(id):
    h = Honorario.query.get_or_404(id)
    db.session.delete(h)
    db.session.commit()
    flash('Honorario eliminado.', 'success')
    return redirect(url_for('empleados.honorarios'))

@empleados_bp.route('/honorarios/archivo/<filename>')
@login_required
def archivo_honorario(filename):
    return send_from_directory(UPLOAD_HONORARIOS, filename)
