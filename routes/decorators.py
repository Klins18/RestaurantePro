from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user


PERMISOS_LABELS = {
    'pedidos':     ('📋', 'Listas de pedido'),
    'compras':     ('🛍️', 'Registro de compras'),
    'gas':         ('🔴', 'Balones de gas'),
    'inventario':  ('📦', 'Inventario / Almacén'),
    'asistencia':  ('✅', 'Asistencia y reporte'),
    'reservas':    ('📅', 'Reservas de grupos'),
    'cierre_caja': ('🏁', 'Cierre de caja'),
    'honorarios':  ('💼', 'Honorarios'),
}


def tiene_permiso(permiso):
    """True si el usuario es admin/supervisor O tiene el permiso individual."""
    if not current_user.is_authenticated:
        return False
    if current_user.rol in ('administrador', 'supervisor'):
        return True
    return current_user.permisos.filter_by(permiso=permiso).first() is not None


def get_permisos_usuario(usuario):
    """Retorna set de permisos de un usuario."""
    return {p.permiso for p in usuario.permisos.all()}


def admin_required(f):
    """Solo administrador."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'administrador':
            flash('Acceso restringido. Se requiere rol de Administrador.', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


def supervisor_required(f):
    """Administrador o Supervisor."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol not in ('administrador', 'supervisor'):
            flash('Acceso restringido. Se requiere rol de Supervisor o Administrador.', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


def permiso_required(permiso):
    """Admin/supervisor O usuario con permiso individual."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if tiene_permiso(permiso):
                return f(*args, **kwargs)
            flash(f'No tienes permiso para acceder a esta sección.', 'error')
            return redirect(url_for('main.dashboard'))
        return decorated
    return decorator


def es_admin():
    return current_user.is_authenticated and current_user.rol == 'administrador'


def es_supervisor():
    return current_user.is_authenticated and current_user.rol in ('administrador', 'supervisor')
