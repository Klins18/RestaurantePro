from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Usuario, Categoria, Producto, Proveedor, Auditoria, registrar_auditoria
from functools import wraps

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.es_admin():
            flash('Acceso restringido al administrador.', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated

# ──────────────────────────────────────
#  PANEL ADMINISTRACIÓN
# ──────────────────────────────────────
@admin_bp.route('/')
@login_required
@admin_required
def index():
    return render_template('admin/index.html')

# ──────────────────────────────────────
#  USUARIOS
# ──────────────────────────────────────
@admin_bp.route('/usuarios')
@login_required
@admin_required
def usuarios():
    users = Usuario.query.order_by(Usuario.nombre_completo).all()
    return render_template('admin/usuarios.html', usuarios=users)

@admin_bp.route('/usuarios/nuevo', methods=['POST'])
@login_required
@admin_required
def nuevo_usuario():
    username = request.form.get('username', '').strip().lower()
    nombre = request.form.get('nombre_completo', '').strip()
    password = request.form.get('password', '')
    rol = request.form.get('rol', 'empleado')

    if not username or not nombre or not password:
        flash('Todos los campos son obligatorios.', 'error')
        return redirect(url_for('admin.usuarios'))

    if Usuario.query.filter_by(username=username).first():
        flash(f'El usuario "{username}" ya existe.', 'error')
        return redirect(url_for('admin.usuarios'))

    user = Usuario(
        username=username,
        nombre_completo=nombre,
        rol=rol,
        creado_por_id=current_user.id
    )
    user.set_password(password)
    db.session.add(user)
    registrar_auditoria(current_user.id, 'CREAR_USUARIO', 'usuarios',
                        detalle=f'Nuevo usuario: {username} | Rol: {rol}',
                        ip=request.remote_addr)
    db.session.commit()
    flash(f'Usuario "{username}" creado exitosamente.', 'success')
    return redirect(url_for('admin.usuarios'))

@admin_bp.route('/usuarios/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_usuario(id):
    user = Usuario.query.get_or_404(id)
    nombre = request.form.get('nombre_completo', '').strip()
    rol = request.form.get('rol', 'empleado')
    activo = request.form.get('activo') == 'on'
    password = request.form.get('password', '').strip()

    if id == current_user.id and rol != 'administrador':
        flash('No puedes quitarte el rol de administrador.', 'error')
        return redirect(url_for('admin.usuarios'))

    user.nombre_completo = nombre
    user.rol = rol
    user.activo = activo
    if password:
        user.set_password(password)

    registrar_auditoria(current_user.id, 'EDITAR_USUARIO', 'usuarios', id,
                        f'Usuario: {user.username}', ip=request.remote_addr)
    db.session.commit()
    flash(f'Usuario "{user.username}" actualizado.', 'success')
    return redirect(url_for('admin.usuarios'))

# ──────────────────────────────────────
#  TOGGLE ACTIVO USUARIO
# ──────────────────────────────────────
@admin_bp.route('/usuarios/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_usuario(id):
    user = Usuario.query.get_or_404(id)
    if user.id == current_user.id:
        flash('No puedes desactivarte a ti mismo.', 'error')
    else:
        user.activo = not user.activo
        db.session.commit()
        flash(f'Usuario {"activado" if user.activo else "desactivado"}.', 'success')
    return redirect(url_for('admin.usuarios'))

# ──────────────────────────────────────
#  CATEGORÍAS
# ──────────────────────────────────────
@admin_bp.route('/categorias')
@login_required
@admin_required
def categorias():
    cats = Categoria.query.order_by(Categoria.nombre).all()
    return render_template('admin/categorias.html', categorias=cats)

@admin_bp.route('/categorias/nueva', methods=['POST'])
@login_required
@admin_required
def nueva_categoria():
    nombre = request.form.get('nombre', '').strip()
    desc = request.form.get('descripcion', '').strip()
    if not nombre:
        flash('El nombre es obligatorio.', 'error')
        return redirect(url_for('admin.categorias'))
    cat = Categoria(nombre=nombre, descripcion=desc)
    db.session.add(cat)
    db.session.commit()
    flash(f'Categoría "{nombre}" creada.', 'success')
    return redirect(url_for('admin.categorias'))

@admin_bp.route('/categorias/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_categoria(id):
    cat = Categoria.query.get_or_404(id)
    cat.nombre = request.form.get('nombre', cat.nombre).strip()
    cat.descripcion = request.form.get('descripcion', '').strip()
    db.session.commit()
    flash(f'Categoría actualizada.', 'success')
    return redirect(url_for('admin.categorias'))

@admin_bp.route('/categorias/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def eliminar_categoria(id):
    cat = Categoria.query.get_or_404(id)
    # Verificar si tiene productos
    if cat.productos:
        flash(f'No se puede eliminar: la categoría tiene {len(cat.productos)} producto(s). Muévelos primero.', 'error')
        return redirect(url_for('admin.categorias'))
    db.session.delete(cat)
    db.session.commit()
    flash('Categoría eliminada.', 'success')
    return redirect(url_for('admin.categorias'))

# ──────────────────────────────────────
#  PRODUCTOS
# ──────────────────────────────────────
@admin_bp.route('/productos')
@login_required
@admin_required
def productos():
    prods = Producto.query.order_by(Producto.nombre).all()
    cats = Categoria.query.filter_by(activo=True).order_by(Categoria.nombre).all()
    UNIDADES = ['kg', 'gramos', 'litro', 'ml', 'unidad', 'caja', 'bolsa',
                'saco', 'galon', 'atado', 'docena', 'barra', 'sobre']
    return render_template('admin/productos.html', productos=prods, categorias=cats, unidades=UNIDADES)

@admin_bp.route('/productos/nuevo', methods=['POST'])
@login_required
@admin_required
def nuevo_producto():
    nombre = request.form.get('nombre', '').strip()
    unidad = request.form.get('unidad_medida', 'unidad')
    cat_id = request.form.get('categoria_id') or None
    stock_min_str = request.form.get('stock_minimo', '0')

    if not nombre:
        flash('El nombre es obligatorio.', 'error')
        return redirect(url_for('admin.productos'))

    try:
        stock_min = float(stock_min_str)
    except:
        stock_min = 0

    prod = Producto(nombre=nombre, unidad_medida=unidad,
                    categoria_id=cat_id, stock_minimo=stock_min)
    db.session.add(prod)
    db.session.commit()
    flash(f'Producto "{nombre}" creado.', 'success')
    return redirect(url_for('admin.productos'))

@admin_bp.route('/productos/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_producto(id):
    prod = Producto.query.get_or_404(id)
    prod.nombre = request.form.get('nombre', prod.nombre).strip()
    prod.unidad_medida = request.form.get('unidad_medida', prod.unidad_medida)
    prod.categoria_id = request.form.get('categoria_id') or None
    try:
        prod.stock_minimo = float(request.form.get('stock_minimo', 0))
    except:
        pass
    prod.activo = request.form.get('activo') == 'on'
    db.session.commit()
    flash(f'Producto "{prod.nombre}" actualizado.', 'success')
    return redirect(url_for('admin.productos'))

# ──────────────────────────────────────
#  PROVEEDORES
# ──────────────────────────────────────
@admin_bp.route('/proveedores')
@login_required
@admin_required
def proveedores():
    provs = Proveedor.query.order_by(Proveedor.nombre).all()
    return render_template('admin/proveedores.html', proveedores=provs)

@admin_bp.route('/proveedores/nuevo', methods=['POST'])
@login_required
@admin_required
def nuevo_proveedor():
    nombre = request.form.get('nombre', '').strip()
    ruc = request.form.get('ruc', '').strip()
    tel = request.form.get('telefono', '').strip()
    email = request.form.get('email', '').strip()
    dir_ = request.form.get('direccion', '').strip()

    if not nombre:
        flash('El nombre es obligatorio.', 'error')
        return redirect(url_for('admin.proveedores'))

    prov = Proveedor(nombre=nombre, ruc=ruc, telefono=tel, email=email, direccion=dir_)
    db.session.add(prov)
    db.session.commit()
    flash(f'Proveedor "{nombre}" creado.', 'success')
    return redirect(url_for('admin.proveedores'))

# ──────────────────────────────────────
#  AUDITORÍA
# ──────────────────────────────────────
@admin_bp.route('/auditoria')
@login_required
@admin_required
def auditoria():
    registros = Auditoria.query.order_by(Auditoria.fecha_hora.desc()).limit(300).all()
    return render_template('admin/auditoria.html', registros=registros)
