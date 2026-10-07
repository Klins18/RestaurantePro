from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Usuario, Categoria, Producto, Proveedor, Auditoria, registrar_auditoria, now_peru
from services.units import INVENTORY_UNIT_CHOICES, normalize_unit
from functools import wraps
import math

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
UNIDADES_PRODUCTO = {option['value'] for option in INVENTORY_UNIT_CHOICES}


def _producto_duplicado(nombre, unidad, categoria_id, excluir_id=None):
    consulta = Producto.query.filter(
        db.func.lower(db.func.trim(Producto.nombre)) == nombre.lower(),
        Producto.unidad_medida == unidad,
        Producto.categoria_id == categoria_id,
        Producto.activo.is_(True),
    )
    if excluir_id is not None:
        consulta = consulta.filter(Producto.id != excluir_id)
    return consulta.first()


def _ajustar_stock_vino(producto, unidades, referencia, concepto):
    """Ajusta stock, movimientos y kardex dentro de la misma transacción."""
    if not unidades:
        return
    from models import MovimientoAlmacen
    from services.kardex import registrar_kardex
    tipo = 'egreso' if unidades > 0 else 'ingreso'
    cantidad = abs(unidades)
    producto.stock_actual = (producto.stock_actual or 0) - unidades
    db.session.add(MovimientoAlmacen(
        tipo=tipo, producto_id=producto.id, cantidad=cantidad,
        unidad_medida=producto.unidad_medida, motivo=concepto,
        referencia=referencia, usuario_id=current_user.id, fecha_hora=now_peru(),
    ))
    registrar_kardex(producto.id, tipo, cantidad, current_user.id,
                     concepto=concepto, referencia=referencia, fecha=now_peru())

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

    if len(password) < 8 or rol not in {'empleado', 'supervisor', 'administrador'}:
        flash('La contraseña debe tener al menos 8 caracteres y el rol debe ser válido.', 'error')
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
    if rol not in {'empleado', 'supervisor', 'administrador'}:
        flash('El rol seleccionado no es válido.', 'error')
        return redirect(url_for('admin.usuarios'))
    if password and len(password) < 8:
        flash('La contraseña debe tener al menos 8 caracteres.', 'error')
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
    cats = Categoria.query.filter_by(activo=True).order_by(Categoria.nombre).all()
    # Agrupar productos por categoría
    por_categoria = []
    for cat in cats:
        prods = Producto.query.filter_by(categoria_id=cat.id, activo=True).order_by(Producto.nombre).all()
        if prods:
            for prod in prods:
                prod.unidad_ui = normalize_unit(prod.unidad_medida)
            por_categoria.append({'cat': cat, 'productos': prods})
    # Sin categoría
    sin_cat = Producto.query.filter_by(categoria_id=None, activo=True).order_by(Producto.nombre).all()
    if sin_cat:
        for prod in sin_cat:
            prod.unidad_ui = normalize_unit(prod.unidad_medida)
        por_categoria.append({'cat': None, 'productos': sin_cat})
    return render_template('admin/productos.html',
                           por_categoria=por_categoria,
                           categorias=cats, unidades=INVENTORY_UNIT_CHOICES)

@admin_bp.route('/productos/nuevo', methods=['POST'])
@login_required
@admin_required
def nuevo_producto():
    nombre = request.form.get('nombre', '').strip()
    unidad = normalize_unit(request.form.get('unidad_medida', 'unidad'))
    cat_id_raw = request.form.get('categoria_id', '').strip()
    stock_min_str = request.form.get('stock_minimo', '0')
    costo_raw = request.form.get('costo_unitario', '').strip()

    if not nombre:
        flash('El nombre es obligatorio.', 'error')
        return redirect(url_for('admin.productos'))
    if len(nombre) > 150 or unidad not in UNIDADES_PRODUCTO:
        flash('Revisa el nombre y la unidad del producto.', 'error')
        return redirect(url_for('admin.productos'))
    try:
        cat_id = int(cat_id_raw) if cat_id_raw else None
    except (TypeError, ValueError, OverflowError):
        cat_id = -1
    if cat_id is not None and not db.session.get(Categoria, cat_id):
        flash('La categoría seleccionada ya no existe. Actualiza la página y vuelve a elegirla.', 'error')
        return redirect(url_for('admin.productos'))
    if _producto_duplicado(nombre, unidad, cat_id):
        flash('Ya existe un producto activo con el mismo nombre, categoría y unidad. Edita el existente para evitar dividir el stock.', 'error')
        return redirect(url_for('admin.productos'))

    try:
        stock_min = float(stock_min_str)
        if stock_min < 0 or not math.isfinite(stock_min):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        flash('El stock mínimo debe ser un número válido y no negativo.', 'error')
        return redirect(url_for('admin.productos'))

    try:
        costo_unitario = float(costo_raw) if costo_raw else None
        if costo_unitario is not None and (costo_unitario < 0 or not math.isfinite(costo_unitario)):
            raise ValueError
    except ValueError:
        flash('El costo unitario debe ser un monto igual o mayor que cero.', 'error')
        return redirect(url_for('admin.productos'))

    prod = Producto(nombre=nombre, unidad_medida=unidad,
                    categoria_id=cat_id, stock_minimo=stock_min,
                    costo_unitario=costo_unitario)
    db.session.add(prod)
    db.session.commit()
    flash(f'Producto "{nombre}" creado.', 'success')
    return redirect(url_for('admin.productos'))

@admin_bp.route('/productos/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_producto(id):
    prod = Producto.query.get_or_404(id)
    nombre = request.form.get('nombre', prod.nombre).strip()
    unidad = normalize_unit(request.form.get('unidad_medida', prod.unidad_medida))
    cat_id_raw = request.form.get('categoria_id', '').strip()
    try:
        cat_id = int(cat_id_raw) if cat_id_raw else None
    except (TypeError, ValueError, OverflowError):
        cat_id = -1
    if not nombre or len(nombre) > 150 or (unidad not in UNIDADES_PRODUCTO and unidad != prod.unidad_medida):
        flash('Revisa el nombre y la unidad del producto.', 'error')
        return redirect(url_for('admin.productos'))
    if cat_id is not None and not db.session.get(Categoria, cat_id):
        flash('La categoría seleccionada no existe.', 'error')
        return redirect(url_for('admin.productos'))
    if _producto_duplicado(nombre, unidad, cat_id, excluir_id=prod.id):
        flash('Ya existe otro producto activo con ese nombre, categoría y unidad. No se guardaron los cambios.', 'error')
        return redirect(url_for('admin.productos'))
    try:
        stock_minimo = float(request.form.get('stock_minimo', 0))
        if stock_minimo < 0 or not math.isfinite(stock_minimo):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        flash('El stock mínimo debe ser un número válido y no negativo.', 'error')
        return redirect(url_for('admin.productos'))
    costo_raw = request.form.get('costo_unitario', '').strip()
    try:
        costo = float(costo_raw) if costo_raw else None
        if costo is not None and (costo < 0 or not math.isfinite(costo)):
            raise ValueError
        prod.costo_unitario = costo
    except ValueError:
        flash('El costo unitario debe ser un monto igual o mayor que cero.', 'error')
        return redirect(url_for('admin.productos'))
    prod.nombre = nombre
    prod.unidad_medida = unidad
    prod.categoria_id = cat_id
    prod.stock_minimo = stock_minimo
    prod.activo = request.form.get('activo', 'on') == 'on'
    db.session.commit()
    flash(f'Producto "{prod.nombre}" actualizado.', 'success')
    return redirect(url_for('admin.productos'))

@admin_bp.route('/productos/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def eliminar_producto(id):
    prod = Producto.query.get_or_404(id)
    nombre = prod.nombre
    prod.activo = False
    db.session.commit()
    flash(f'Producto "{nombre}" desactivado.', 'success')
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


# ──────────────────────────────────────────────
#  GESTIÓN DE PERMISOS POR USUARIO
# ──────────────────────────────────────────────
@admin_bp.route('/permisos')
@login_required
@admin_required
def permisos():
    from routes.decorators import PERMISOS_LABELS, get_permisos_usuario
    usuarios = Usuario.query.filter(Usuario.rol == 'empleado').order_by(Usuario.nombre_completo).all()
    permisos_map = {u.id: get_permisos_usuario(u) for u in usuarios}
    return render_template('admin/permisos.html',
                           usuarios=usuarios,
                           permisos_map=permisos_map,
                           permisos_labels=PERMISOS_LABELS)


@admin_bp.route('/permisos/<int:usuario_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_permiso(usuario_id):
    from models import PermisoUsuario
    from routes.decorators import PERMISOS_LABELS
    permiso = request.form.get('permiso')
    if permiso not in PERMISOS_LABELS:
        flash('Permiso inválido.', 'error')
        return redirect(url_for('admin.permisos'))

    usuario = Usuario.query.get_or_404(usuario_id)
    existente = PermisoUsuario.query.filter_by(usuario_id=usuario_id, permiso=permiso).first()

    if existente:
        db.session.delete(existente)
        flash(f'Permiso "{PERMISOS_LABELS[permiso][1]}" removido de {usuario.username}.', 'success')
    else:
        db.session.add(PermisoUsuario(
            usuario_id=usuario_id, permiso=permiso,
            otorgado_por=current_user.id
        ))
        flash(f'Permiso "{PERMISOS_LABELS[permiso][1]}" asignado a {usuario.username}.', 'success')

    db.session.commit()
    return redirect(url_for('admin.permisos'))


# ──────────────────────────────────────────────────────
#  PRODUCTOS DE CARTA (vinculación con almacén)
# ──────────────────────────────────────────────────────
@admin_bp.route('/carta')
@login_required
@admin_required
def carta():
    from models import CategoriaCarta, ProductoCarta, Producto
    categorias = CategoriaCarta.query.order_by(CategoriaCarta.orden).all()
    productos_almacen = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    return render_template('admin/carta.html',
                           categorias=categorias,
                           productos_almacen=productos_almacen)


@admin_bp.route('/carta/<int:id>/vincular', methods=['POST'])
@login_required
@admin_required
def vincular_carta(id):
    from models import ProductoCarta, Producto
    prod = ProductoCarta.query.get_or_404(id)
    descuenta = request.form.get('descuenta_inventario') == 'on'
    alm_id = request.form.get('producto_almacen_id') or None

    # Si marca descuenta pero no selecciona producto de almacén,
    # crear automáticamente el producto en almacén
    if descuenta and not alm_id:
        existente = Producto.query.filter(
            Producto.nombre.ilike(f'%{prod.nombre}%')
        ).first()
        if existente:
            alm_id = existente.id
        else:
            from models import Categoria
            cat = Categoria.query.filter_by(nombre='Bebidas').first()
            if not cat:
                cat = Categoria.query.filter_by(activo=True).first()
            nuevo_prod = Producto(
                nombre=prod.nombre,
                unidad_medida='unidad',
                categoria_id=cat.id if cat else None,
                stock_actual=0, stock_minimo=0, activo=True
            )
            db.session.add(nuevo_prod)
            db.session.flush()
            alm_id = nuevo_prod.id
            flash(f'Producto "{prod.nombre}" creado en almacén.', 'info')

    prod.descuenta_inventario = descuenta
    prod.producto_almacen_id = int(alm_id) if alm_id else None
    db.session.commit()
    flash(f'"{prod.nombre}" actualizado.', 'success')
    return redirect(url_for('admin.carta'))


@admin_bp.route('/carta/categoria/nueva', methods=['POST'])
@login_required
@admin_required
def nueva_categoria_carta():
    from models import CategoriaCarta
    nombre = request.form.get('nombre', '').strip()
    if nombre:
        orden = db.session.query(db.func.max(CategoriaCarta.orden)).scalar() or 0
        db.session.add(CategoriaCarta(nombre=nombre, orden=orden+1, activo=True))
        db.session.commit()
        flash(f'Categoría "{nombre}" creada.', 'success')
    return redirect(url_for('admin.carta'))


@admin_bp.route('/carta/producto/nuevo', methods=['POST'])
@login_required
@admin_required
def nuevo_producto_carta():
    from models import ProductoCarta, CategoriaCarta
    nombre = request.form.get('nombre', '').strip()
    cat_id = request.form.get('categoria_id')
    try:
        precio = float(request.form.get('precio', 0) or 0)
        categoria_id = int(cat_id) if cat_id else None
        if precio < 0 or not math.isfinite(precio) or not nombre or not categoria_id:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        flash('Indica un nombre, categoría válida y precio no negativo.', 'error')
        return redirect(url_for('admin.carta'))
    if not db.session.get(CategoriaCarta, categoria_id):
        flash('La categoría seleccionada no existe.', 'error')
        return redirect(url_for('admin.carta'))
    if nombre and categoria_id:
        orden = db.session.query(db.func.max(ProductoCarta.orden)).scalar() or 0
        db.session.add(ProductoCarta(
            nombre=nombre, categoria_id=categoria_id,
            precio=precio, activo=True, orden=orden+1
        ))
        db.session.commit()
        flash(f'Producto "{nombre}" agregado a la carta.', 'success')
    return redirect(url_for('admin.carta'))

# ──────────────────────────────────────────────────────
#  VINOS — configuración copas por botella
# ──────────────────────────────────────────────────────
@admin_bp.route('/carta/<int:id>/configurar-vino', methods=['POST'])
@login_required
@admin_required
def configurar_vino(id):
    from models import ProductoCarta
    prod = ProductoCarta.query.get_or_404(id)
    try:
        copas = int(request.form.get('copas_por_botella', 5))
        precio_copa = float(request.form.get('precio_copa', 0) or 0)
        precio_botella = float(request.form.get('precio_botella', 0) or 0)
        if copas < 1 or min(precio_copa, precio_botella) < 0 or not all(
            map(math.isfinite, (precio_copa, precio_botella))
        ):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        flash('Copas y precios deben ser valores válidos; las copas deben ser al menos una.', 'error')
        return redirect(url_for('admin.carta'))
    prod.es_vino = request.form.get('es_vino') == 'on'
    prod.copas_por_botella = copas
    prod.precio_copa = precio_copa
    prod.precio_botella = precio_botella
    db.session.commit()
    flash(f'Configuración de vino actualizada para "{prod.nombre}".', 'success')
    return redirect(url_for('admin.carta'))


@admin_bp.route('/vinos/registros')
@login_required
@admin_required
def registros_botella():
    from models import RegistroBotella, ProductoCarta
    from datetime import date
    fecha_str = request.args.get('fecha', now_peru().date().strftime('%Y-%m-%d'))
    try:
        from datetime import datetime
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except:
        fecha = now_peru().date()
    registros = RegistroBotella.query.filter_by(fecha=fecha).all()
    # Productos de vino
    vinos = ProductoCarta.query.filter_by(es_vino=True, activo=True).all()
    return render_template('admin/registros_botella.html',
                           registros=registros, vinos=vinos,
                           fecha=fecha, fecha_str=fecha_str)


@admin_bp.route('/vinos/confirmar', methods=['POST'])
@login_required
@admin_required
def confirmar_botella():
    from models import RegistroBotella, ProductoCarta, Producto
    from datetime import date, datetime
    try:
        prod_id = int(request.form.get('producto_carta_id'))
        n_bot_enteras = int(request.form.get('botellas_enteras', 0) or 0)
        if n_bot_enteras < 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        flash('Selecciona un vino válido e indica una cantidad de botellas no negativa.', 'error')
        return redirect(url_for('admin.registros_botella'))
    fecha_str= request.form.get('fecha')
    try: fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except: fecha = now_peru().date()

    vacia    = request.form.get('botella_vacia') == 'si'
    notas    = request.form.get('notas', '').strip()
    pc = ProductoCarta.query.get_or_404(prod_id)
    reg = RegistroBotella.query.filter_by(
        producto_carta_id=prod_id, fecha=fecha).first()
    if not reg:
        reg = RegistroBotella(producto_carta_id=prod_id, fecha=fecha,
                              creado_en=now_peru(), usuario_id=current_user.id)
        db.session.add(reg)
        db.session.flush()

    unidades_antes = (1 if reg.botella_vacia else 0) + (reg.botellas_vendidas_enteras or 0)
    unidades_ahora = (1 if vacia else 0) + n_bot_enteras
    diferencia = unidades_ahora - unidades_antes
    prod_alm = db.session.get(Producto, pc.producto_almacen_id) if pc.producto_almacen_id and pc.descuenta_inventario else None
    if diferencia > 0 and prod_alm and (prod_alm.stock_actual or 0) < diferencia:
        flash(f'Stock insuficiente de {prod_alm.nombre} para confirmar el consumo.', 'error')
        return redirect(url_for('admin.registros_botella', fecha=fecha_str))

    reg.botella_vacia             = vacia
    reg.botellas_vendidas_enteras = n_bot_enteras
    reg.notas                     = notas
    reg.confirmado_por            = current_user.id

    if prod_alm:
        _ajustar_stock_vino(prod_alm, diferencia,
                            f'VINO-{reg.id}-{fecha.isoformat()}',
                            f'Ajuste de consumo de vino — registro #{reg.id}')

    db.session.commit()
    flash('Registro de botella guardado.', 'success')
    return redirect(url_for('admin.registros_botella', fecha=fecha_str))


@admin_bp.route('/vinos/editar/<int:reg_id>', methods=['POST'])
@login_required
@admin_required
def editar_registro_botella(reg_id):
    from models import RegistroBotella, Producto, ProductoCarta
    reg = RegistroBotella.query.get_or_404(reg_id)
    vacia_antes = reg.botella_vacia
    vacia_nueva = request.form.get('botella_vacia') == 'si'
    reg.botella_vacia = vacia_nueva
    reg.notas = request.form.get('notas', '').strip()
    reg.confirmado_por = current_user.id

    # Ajustar solo la diferencia, así volver a confirmar no duplica el consumo.
    pc = db.session.get(ProductoCarta, reg.producto_carta_id)
    if pc and pc.producto_almacen_id and pc.descuenta_inventario:
        prod_alm = db.session.get(Producto, pc.producto_almacen_id)
        if prod_alm:
            diferencia = int(vacia_nueva) - int(bool(vacia_antes))
            if diferencia > 0 and (prod_alm.stock_actual or 0) < diferencia:
                flash('No hay stock suficiente para ajustar la botella confirmada.', 'error')
                return redirect(request.referrer or url_for('admin.registros_botella'))
            _ajustar_stock_vino(prod_alm, diferencia,
                                f'VINO-EDICION-{reg.id}-{int(now_peru().timestamp())}',
                                f'Ajuste al editar registro de vino #{reg.id}')

    db.session.commit()
    flash('Registro actualizado.', 'success')
    return redirect(request.referrer or url_for('admin.registros_botella'))
