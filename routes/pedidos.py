import os
import math
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, current_app
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, ListaPedido, ItemPedido, ComprobantePedido, Usuario, Producto, MovimientoAlmacen, Notificacion, registrar_auditoria
from services.kardex import registrar_kardex
from services.units import UNIT_CHOICES, normalize_unit
from datetime import datetime, date
import pytz
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

pedidos_bp = Blueprint('pedidos', __name__, url_prefix='/pedidos')
PERU_TZ = pytz.timezone('America/Lima')

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

UPLOAD_COMPROBANTES = 'uploads/comprobantes_pedido'
ALLOWED_EXT = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}

def guardar_comprobante(file):
    if file and file.filename and '.' in file.filename:
        ext = file.filename.rsplit('.', 1)[1].lower()
        if ext in ALLOWED_EXT:
            folder = os.path.join(current_app.instance_path, UPLOAD_COMPROBANTES)
            os.makedirs(folder, exist_ok=True)
            fname = f'{uuid.uuid4().hex}.{ext}'
            file.save(os.path.join(folder, fname))
            return fname
    return None

# ── PRODUCTOS PREDEFINIDOS POR TIPO ────────────────────────────
LISTAS_PREDEFINIDAS = {
    'VERDURA FRESCA': [
        ('APIO', '@'), ('ZANAHORIA', '@'), ('VETERRAGA', '@'), ('CEBOLLA', '@'),
        ('ARVEJAS', 'kg'), ('VAINITAS', 'kg'), ('PEPINILLO', '@'),
        ('REPOLLO', 'unid'), ('BROCOLY', 'kg'), ('COLIFLOR', 'unid'),
        ('LIMON', 'kg'), ('LECHUGA', 'unid'), ('COL MORADO', 'unid'),
        ('ROCOTO', ''), ('AJO PELADO', 'kg'), ('CAMOTE', '@'),
        ('TOMATE', 'caja'), ('ZAPALLO', 'kg'), ('HABAS', '@'),
        ('CAIGUA', 'unid'), ('MAIZ MORADO', 'kg'), ('ALBACA', 'S/.'),
        ('ESPINACA', 'S/.'), ('NABO', 'S/.'), ('CHOCLOS', 'unid'),
        ('ACELGA', 'atado'), ('YUCA', 'kg'), ('PORO', 'S/.'),
        ('KION', ''), ('PIMENTON', 'kg'), ('CEBOLLA CHINA', 'und'),
        ('HOLANTAO', ''),
    ],
    'FRUTAS/BOMBONERA': [
        ('PLATANOS', 'unid'), ('PALTA', 'kg'), ('PAPAYA', ''),
        ('PIÑA', 'unid'), ('COCA', ''), ('MANZANA DELICIA', 'kg'),
        ('NARANJAS', ''), ('LIZAS LARGAS', 'kg'), ('LIZAS CUADRADAS', ''),
        ('PATASQUITA MIXTO', ''), ('MAIZ PELADO (SARA PELA)', 'S/.'),
        ('TARWI MOLIDO', 'kg'), ('QUESO', 'unid'), ('PAPA PERUANITA', '@'),
        ('PAPA PARA PELAR', ''), ('HIERVAS', 'S/.'), ('CILANDRO', 'S/.'),
        ('OCAS', ''), ('SANDIA', 'unid'), ('MANZANA DELICIA VERDE', 'kg'),
    ],
    'CARNES': [
        ('PECHUGA DE POLLO', 'caja'), ('BOTELLITAS DE POLLO', 'unid'),
        ('PESCADO', 'caja'), ('PULPA DE CERDO', 'kg'),
        ('PANCETA DE CERDO', 'kg'), ('PULPA DE RES', 'kg'),
        ('BISTECK', 'kg'), ('MANZANA - HUESO', 'kg'),
        ('CARNE PICADA', ''),
    ],
    'ABARROTES E INSUMOS DE LIMPIEZA': [
        ('FIDEO TORNILLO', ''), ('ACEITE', ''), ('SPAGUETTI', ''),
        ('FLAN', 'pqt'), ('GELATINA', ''), ('MANTEQUILLA', 'barra'),
        ('TORTA', 'unid'), ('WANTAN', 'unid'), ('MAYONESA', 'caja'),
        ('ALGARROBINA', 'unid'), ('MAIZ BLANCO', 'kg'), ('MANDIOCA', 'kg'),
        ('PASAS', 'kg'), ('SOYA', ''), ('COCO RALLADO', 'kg'),
        ('CAÑIHUA', ''), ('TUCO', 'unid'), ('VINAGRE TINTO', ''),
        ('VINAGRE BLANCO', ''), ('GARBANZO', 'saco'), ('QUINUA', '@'),
        ('CHUÑO', ''), ('PIMIENTA MOLIDA', ''), ('COMINO MOLIDO', ''),
        ('TAMPICO', ''), ('BOLSA 0.10', 'pqt'), ('TE DE MANZANILLA', ''),
        ('TE CANELA Y CLAVO', 'caja'), ('TE PURO', ''), ('TE MUÑA', ''),
        ('LECHE ENTERA', 'caja'), ('ALCOHOL', 'galon'), ('DETERGENTE', ''),
        ('AYUDIN', 'unid'), ('LEJIA', ''), ('PERIODICO', 'kg'),
        ('HIGO SECO', 'und'), ('POLVO DE HORNEAR', ''), ('MAZAMORRA MORADA', ''),
    ],
}

LISTAS_PREDEFINIDAS['COCA COLA / BEBIDAS'] = [
    # Gaseosas Coca Cola
    ('GASEOSA 700ML COCA COLA', 'caja'), ('GASEOSA 700ML INKA COLA', 'caja'),
    ('GASEOSA 700ML FANTA', 'caja'), ('GASEOSA 700ML SPRITE', 'caja'),
    ('GASEOSA 300ML COCA COLA', 'caja'), ('GASEOSA 300ML INKA COLA ZERO', 'caja'),
    # Aguas
    ('AGUA 750ML CON GAS', 'caja'), ('AGUA 750ML SIN GAS', 'caja'),
    # Cervezas
    ('CERVEZA CUSQUEÑA DORADA', 'caja'), ('CERVEZA CUSQUEÑA TRIGO', 'caja'),
    ('CERVEZA CUSQUEÑA NEGRA', 'caja'), ('PILSEN LATA GRANDE', 'caja'),
    ('PILSEN LATA PEQUEÑA', 'caja'), ('BUDWEISER', 'caja'), ('HEINEKEN', 'caja'),
    # Vinos
    ('VINO TINTO', 'botella'), ('VINO BLANCO', 'botella'), ('VINO PEQUEÑO', 'botella'),
]

TIPOS_REQUERIMIENTO = list(LISTAS_PREDEFINIDAS.keys()) + ['LÁCTEOS Y DERIVADOS', 'OTROS']

# ──────────────────────────────────────
#  LISTAR
# ──────────────────────────────────────
@pedidos_bp.route('/')
@login_required
@permiso_required('pedidos')
def index():
    estado = request.args.get('estado', '')
    tipo = request.args.get('tipo', '')
    q = ListaPedido.query.order_by(ListaPedido.elaborado_en.desc())
    if estado: q = q.filter_by(estado=estado)
    if tipo:   q = q.filter_by(tipo_requerimiento=tipo)
    pagina = q.options(
        selectinload(ListaPedido.items),
        joinedload(ListaPedido.elaborado_por),
        joinedload(ListaPedido.verificado_por),
    ).paginate(page=request.args.get('page', 1, type=int), per_page=50, error_out=False)
    return render_template('pedidos/index.html', listas=pagina.items, pagina=pagina,
                           tipos=TIPOS_REQUERIMIENTO,
                           estado_filtro=estado, tipo_filtro=tipo)

# ──────────────────────────────────────
#  NUEVA LISTA
# ──────────────────────────────────────
@pedidos_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
@permiso_required('pedidos')
def nueva():
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        tipo = request.form.get('tipo_requerimiento', '')
        fecha_str = request.form.get('fecha', '')
        observaciones = request.form.get('observaciones', '')

        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha = now_peru().date()

        lista = ListaPedido(
            titulo=titulo or f"Pedido {tipo} - {fecha.strftime('%d/%m/%Y')}",
            tipo_requerimiento=tipo, fecha=fecha, estado='pendiente',
            elaborado_por_id=current_user.id,
            elaborado_en=now_peru(), observaciones=observaciones
        )
        db.session.add(lista)
        db.session.flush()

        nombres   = request.form.getlist('item_nombre[]')
        unidades  = request.form.getlist('item_unidad[]')
        cantidades = request.form.getlist('item_cantidad[]')
        precios   = request.form.getlist('item_precio[]')
        obs_items = request.form.getlist('item_obs[]')

        predefinidos = LISTAS_PREDEFINIDAS.get(tipo, [])
        orden = 0
        for i, nombre in enumerate(nombres):
            nombre = nombre.strip()
            es_extra = i >= len(predefinidos)
            if es_extra and not nombre:
                continue

            cantidad_raw = cantidades[i].strip() if i < len(cantidades) else ''
            if not cantidad_raw:
                continue
            try:
                cant = float(cantidad_raw)
                if cant <= 0 or not math.isfinite(cant) or not nombre:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                db.session.rollback()
                flash('Cada artículo debe tener nombre y cantidad válida mayor que cero.', 'error')
                return redirect(url_for('pedidos.nueva'))

            precio_raw = precios[i].strip() if i < len(precios) else ''
            try:
                precio = float(precio_raw) if precio_raw else None
                if precio is not None and (precio < 0 or not math.isfinite(precio)):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                db.session.rollback()
                flash('El precio unitario debe ser válido y no negativo.', 'error')
                return redirect(url_for('pedidos.nueva'))

            item = ItemPedido(
                lista_id=lista.id,
                producto_nombre=nombre,
                unidad_medida=normalize_unit(unidades[i] if i < len(unidades) else ''),
                cantidad_solicitada=cant,
                precio_unitario=precio,
                observacion=obs_items[i] if i < len(obs_items) else '',
                orden=orden
            )
            db.session.add(item)
            orden += 1

        if orden == 0:
            db.session.rollback()
            flash('Agrega al menos un producto con cantidad mayor que cero.', 'error')
            return redirect(url_for('pedidos.nueva'))

        registrar_auditoria(current_user.id, 'CREAR_LISTA_PEDIDO',
                            'listas_pedido', lista.id,
                            f'Lista: {lista.titulo}', ip=request.remote_addr)
        db.session.commit()
        flash('Lista de pedido creada.', 'success')
        return redirect(url_for('pedidos.ver', id=lista.id))

    return render_template('pedidos/nueva.html',
                           tipos=TIPOS_REQUERIMIENTO,
                           listas_predefinidas=LISTAS_PREDEFINIDAS,
                           unidad_options=UNIT_CHOICES,
                           hoy=now_peru().date())

# ──────────────────────────────────────
#  API lista predefinida
# ──────────────────────────────────────
@pedidos_bp.route('/api/lista-predefinida/<tipo>')
@login_required
@permiso_required('pedidos')
def api_lista_predefinida(tipo):
    items = LISTAS_PREDEFINIDAS.get(tipo, [])
    return jsonify([{'nombre': n, 'unid': u} for n, u in items])

# ──────────────────────────────────────
#  VER
# ──────────────────────────────────────
@pedidos_bp.route('/<int:id>')
@login_required
@permiso_required('pedidos')
def ver(id):
    lista = ListaPedido.query.get_or_404(id)
    # Solo items que tienen cantidad o nombre no vacío
    items_con_datos = [i for i in lista.items if i.producto_nombre.strip()]
    return render_template('pedidos/ver.html', lista=lista, items_con_datos=items_con_datos)

# ──────────────────────────────────────
#  VERIFICAR → actualiza stock
# ──────────────────────────────────────
@pedidos_bp.route('/<int:id>/verificar', methods=['GET', 'POST'])
@login_required
@permiso_required('pedidos')
def verificar(id):
    lista = ListaPedido.query.get_or_404(id)

    # ── Empleados Y administradores pueden verificar ──
    if lista.estado not in ('pendiente', 'en_verificacion'):
        flash('Esta lista ya fue completada o aprobada.', 'warning')
        return redirect(url_for('pedidos.ver', id=id))

    if request.method == 'POST':
        irregularidades = []  # Para el reporte

        for item in lista.items:
            verificado    = request.form.get(f'check_{item.id}') == 'on'
            cant_rec_str  = request.form.get(f'cant_{item.id}', '').strip()
            precio_str    = request.form.get(f'precio_{item.id}', '').strip()
            obs           = request.form.get(f'obs_{item.id}', '')

            item.verificado = verificado
            try:
                item.cantidad_recibida = float(cant_rec_str) if cant_rec_str else None
            except:
                db.session.rollback()
                flash('La cantidad recibida debe ser numérica.', 'error')
                return redirect(url_for('pedidos.verificar', id=id))
            if item.cantidad_recibida is not None and (
                item.cantidad_recibida < 0 or not math.isfinite(item.cantidad_recibida)
            ):
                db.session.rollback()
                flash('La cantidad recibida no puede ser negativa ni inválida.', 'error')
                return redirect(url_for('pedidos.verificar', id=id))
            # Si está marcado pero sin cantidad recibida → usar la cantidad solicitada
            if verificado and not item.cantidad_recibida and item.cantidad_solicitada:
                item.cantidad_recibida = item.cantidad_solicitada
            try:
                item.precio_unitario = float(precio_str) if precio_str else item.precio_unitario
            except:
                db.session.rollback()
                flash('El costo unitario debe ser numérico.', 'error')
                return redirect(url_for('pedidos.verificar', id=id))
            if item.precio_unitario is not None and (
                item.precio_unitario < 0 or not math.isfinite(item.precio_unitario)
            ):
                db.session.rollback()
                flash('El costo unitario no puede ser negativo ni inválido.', 'error')
                return redirect(url_for('pedidos.verificar', id=id))
            item.observacion = obs
            # Asignar comprobante si seleccionado
            comp_id_str = request.form.get(f'comp_{item.id}', '').strip()
            item.comprobante_id = int(comp_id_str) if comp_id_str else None

            # ── Detectar irregularidades ──
            nombre = item.producto_nombre.strip()
            if not nombre:
                continue

            sol = item.cantidad_solicitada or 0
            rec = item.cantidad_recibida or 0

            if not verificado and sol > 0:
                irregularidades.append({
                    'item': nombre, 'tipo': 'no_recibido',
                    'detalle': f'No recibido (solicitado: {sol} {item.unidad_medida or ""})',
                    'obs': obs
                })
            elif rec < sol and sol > 0:
                diff = sol - rec
                pct  = round((diff / sol) * 100, 1)
                irregularidades.append({
                    'item': nombre, 'tipo': 'cantidad_menor',
                    'detalle': f'Recibido {rec} de {sol} {item.unidad_medida or ""} — faltan {diff} ({pct}%)',
                    'obs': obs
                })
            elif obs.strip():
                irregularidades.append({
                    'item': nombre, 'tipo': 'con_observacion',
                    'detalle': f'Con observación: {obs}',
                    'obs': obs
                })

            # ── Actualizar stock si verificado con cantidad ──
            if verificado and item.cantidad_recibida and item.cantidad_recibida > 0:
                prod = None
                if item.producto_id:
                    prod = db.session.get(Producto, item.producto_id)
                if not prod:
                    # Buscar por nombre exacto primero, luego parcial
                    nombre_buscar = item.producto_nombre.strip()
                    prod = Producto.query.filter(
                        db.func.lower(Producto.nombre) == nombre_buscar.lower()
                    ).first()
                if not prod:
                    prod = Producto.query.filter(
                        Producto.nombre.ilike(f'%{item.producto_nombre.strip()}%')
                    ).first()

                # ── Si el producto NO existe en el inventario, CREARLO automáticamente ──
                if not prod and item.producto_nombre.strip():
                    from models import Categoria
                    cat_nombre = (lista.tipo_requerimiento or 'General').upper()
                    cat = Categoria.query.filter(func.lower(Categoria.nombre) == cat_nombre.lower()).first()
                    if not cat:
                        try:
                            with db.session.begin_nested():
                                cat = Categoria(nombre=cat_nombre, activo=True)
                                db.session.add(cat)
                                db.session.flush()
                        except IntegrityError:
                            cat = Categoria.query.filter(
                                func.lower(Categoria.nombre) == cat_nombre.lower()
                            ).first()
                    if not cat:
                        cat = Categoria.query.filter_by(activo=True).first()
                    if not cat:
                        db.session.rollback()
                        flash('Crea una categoría de almacén antes de recibir este producto.', 'error')
                        return redirect(url_for('pedidos.verificar', id=id))

                    unidad = normalize_unit(item.unidad_medida) or 'unidad'
                    prod = Producto(
                        nombre=item.producto_nombre.strip(),
                        unidad_medida=unidad,
                        categoria_id=cat.id,
                        stock_actual=0,
                        stock_minimo=0,
                        activo=True,
                        creado_en=now_peru()
                    )
                    db.session.add(prod)
                    db.session.flush()  # Para obtener el ID antes del movimiento
                    # Vincular item al producto recién creado
                    item.producto_id = prod.id

                if prod:
                    if item.precio_unitario and item.precio_unitario > 0:
                        prod.costo_unitario = item.precio_unitario
                    ref_item = f'PEDIDO-{lista.id}-ITEM-{item.id}'
                    movimientos_item = MovimientoAlmacen.query.filter(
                        MovimientoAlmacen.producto_id == prod.id,
                        db.or_(MovimientoAlmacen.referencia == ref_item,
                               MovimientoAlmacen.referencia.like(f'{ref_item}-AJUSTE-%')),
                    ).all()
                    if not movimientos_item:
                        legacy = MovimientoAlmacen.query.filter_by(
                            producto_id=prod.id, referencia=f'PEDIDO-{lista.id}'
                        ).filter(
                            MovimientoAlmacen.motivo.contains(item.producto_nombre[:10])
                        ).first()
                        if legacy:
                            movimientos_item = [legacy]
                    recibido_registrado = sum(
                        m.cantidad if m.tipo == 'ingreso' else -m.cantidad
                        for m in movimientos_item
                    )
                    diferencia = round(item.cantidad_recibida - recibido_registrado, 4)
                    if abs(diferencia) > 0.0001:
                        tipo_mov = 'ingreso' if diferencia > 0 else 'egreso'
                        cantidad_mov = abs(diferencia)
                        referencia_ajuste = ref_item if not movimientos_item else (
                            f'{ref_item}-AJUSTE-{int(now_peru().timestamp())}'
                        )
                        if diferencia < 0 and (prod.stock_actual or 0) < abs(diferencia):
                            db.session.rollback()
                            flash(f'No se puede corregir la recepción: ya se consumieron unidades de "{prod.nombre}".', 'error')
                            return redirect(url_for('pedidos.verificar', id=id))
                        prod.stock_actual = (prod.stock_actual or 0) + diferencia
                        db.session.add(MovimientoAlmacen(
                            tipo=tipo_mov, producto_id=prod.id,
                            cantidad=cantidad_mov,
                            motivo=f'Ajuste de recepción pedido #{lista.id}: {lista.titulo}',
                            referencia=referencia_ajuste, lista_pedido_id=lista.id,
                            usuario_id=current_user.id, fecha_hora=now_peru()
                        ))
                        registrar_kardex(
                            prod.id, tipo_mov, cantidad_mov, current_user.id,
                            concepto=f'Recepción/ajuste pedido #{lista.id}: {lista.titulo}',
                            referencia=referencia_ajuste,
                            fecha=now_peru() if movimientos_item else datetime.combine(lista.fecha, datetime.min.time()),
                            precio_unitario=item.precio_unitario if tipo_mov == 'ingreso' else None,
                        )

        lista.estado = 'en_verificacion'
        lista.verificado_por_id = current_user.id
        lista.verificado_en     = now_peru()

        items_con_nombre = [i for i in lista.items if i.producto_nombre.strip()]
        if items_con_nombre and all(i.verificado for i in items_con_nombre):
            lista.estado = 'completado'

        # ── Generar notificaciones de irregularidades ──
        if irregularidades:
            import json
            lineas = [f"• {ir['item']}: {ir['detalle']}" for ir in irregularidades]
            msg_texto = "\n".join(lineas)
            resumen_titulo = f"⚠️ {len(irregularidades)} irregularidad(es) en pedido #{lista.id}: {lista.titulo}"

            # Notificar a TODOS los administradores
            admins = Usuario.query.filter_by(rol='administrador', activo=True).all()
            for admin in admins:
                if admin.id != current_user.id:
                    n = Notificacion(
                        tipo='irregularidad',
                        titulo=resumen_titulo,
                        mensaje=msg_texto,
                        referencia_id=lista.id,
                        referencia_tipo='pedido',
                        destinatario_id=admin.id,
                        creado_por_id=current_user.id,
                        creado_en=now_peru()
                    )
                    db.session.add(n)

            # También notificar al verificador si es empleado (confirmación de lo que reportó)
            if not current_user.es_admin():
                n_self = Notificacion(
                    tipo='irregularidad',
                    titulo=f"Tu reporte de irregularidades — Pedido #{lista.id}",
                    mensaje=f"Registraste {len(irregularidades)} irregularidad(es):\n{msg_texto}",
                    referencia_id=lista.id,
                    referencia_tipo='pedido',
                    destinatario_id=current_user.id,
                    creado_por_id=current_user.id,
                    creado_en=now_peru()
                )
                db.session.add(n_self)

        registrar_auditoria(current_user.id, 'VERIFICAR_LISTA',
                            'listas_pedido', lista.id,
                            f'Estado: {lista.estado} | Irregularidades: {len(irregularidades)}',
                            ip=request.remote_addr)
        db.session.commit()

        if irregularidades:
            flash(f'✅ Verificación guardada. ⚠️ {len(irregularidades)} irregularidad(es) notificadas al administrador.', 'warning')
        else:
            flash('✅ Verificación guardada. Stock actualizado. Sin irregularidades.', 'success')
        return redirect(url_for('pedidos.ver', id=id))

    return render_template('pedidos/verificar.html', lista=lista)

# ──────────────────────────────────────
#  APROBAR (solo admin)
# ──────────────────────────────────────
@pedidos_bp.route('/<int:id>/aprobar', methods=['POST'])
@login_required
@admin_required
def aprobar(id):
    # La aprobación final queda reservada a administración.
    lista = ListaPedido.query.get_or_404(id)

    if lista.estado not in ('en_verificacion', 'completado', 'pendiente'):
        flash('Esta lista ya fue aprobada.', 'warning')
        return redirect(url_for('pedidos.ver', id=id))

    # Hacer update de stock para ítems verificados que aún no tuvieron movimiento
    items_actualizados = 0
    for item in lista.items:
        if item.verificado and item.cantidad_recibida and item.cantidad_recibida > 0:
            # Verificar si ya se hizo el movimiento durante la verificación
            ref_item = f'PEDIDO-{lista.id}-ITEM-{item.id}'
            mov_existente = MovimientoAlmacen.query.filter(
                db.or_(MovimientoAlmacen.referencia == ref_item,
                       MovimientoAlmacen.referencia.like(f'{ref_item}-AJUSTE-%'),
                       db.and_(MovimientoAlmacen.referencia == f'PEDIDO-{lista.id}',
                               MovimientoAlmacen.motivo.contains(item.producto_nombre[:10])))
            ).first()

            if not mov_existente:
                # Buscar producto y actualizar si no se hizo antes
                prod = None
                if item.producto_id:
                    prod = db.session.get(Producto, item.producto_id)
                if not prod:
                    prod = Producto.query.filter(
                        Producto.nombre.ilike(f'%{item.producto_nombre.strip()}%')
                    ).first()
                if prod:
                    if item.precio_unitario and item.precio_unitario > 0:
                        prod.costo_unitario = item.precio_unitario
                    prod.stock_actual = (prod.stock_actual or 0) + item.cantidad_recibida
                    db.session.add(MovimientoAlmacen(
                        tipo='ingreso',
                        producto_id=prod.id,
                        cantidad=item.cantidad_recibida,
                        motivo=f'Aprobación pedido #{lista.id}: {lista.titulo}',
                        referencia=ref_item,
                        lista_pedido_id=lista.id,
                        usuario_id=current_user.id,
                        fecha_hora=now_peru()
                    ))
                    registrar_kardex(
                        prod.id, 'ingreso', item.cantidad_recibida, current_user.id,
                        concepto=f'Recepción pedido #{lista.id}: {lista.titulo}',
                        referencia=ref_item,
                        fecha=datetime.combine(lista.fecha, datetime.min.time()),
                        precio_unitario=item.precio_unitario,
                    )
                    items_actualizados += 1

    lista.estado = 'aprobado'
    lista.aprobado_por_id = current_user.id
    lista.aprobado_en = now_peru()

    # Notificar al elaborador que su pedido fue aprobado
    try:
        if lista.elaborado_por_id != current_user.id:
            n = Notificacion(
                tipo='info',
                titulo=f'✅ Tu pedido fue aprobado: {lista.titulo}',
                mensaje=f'El pedido #{lista.id} "{lista.titulo}" fue aprobado por {current_user.nombre_completo}.',
                referencia_id=lista.id,
                referencia_tipo='pedido',
                destinatario_id=lista.elaborado_por_id,
                creado_por_id=current_user.id,
                creado_en=now_peru()
            )
            db.session.add(n)
    except:
        pass

    registrar_auditoria(current_user.id, 'APROBAR_LISTA',
                        'listas_pedido', lista.id,
                        f'Stock actualizado: {items_actualizados} ítems adicionales',
                        ip=request.remote_addr)
    db.session.commit()
    msg = f'Lista aprobada y añadida al inventario.'
    if items_actualizados > 0:
        msg += f' ({items_actualizados} ítems actualizados en stock)'
    flash(msg, 'success')
    return redirect(url_for('pedidos.ver', id=id))

# ──────────────────────────────────────
#  ELIMINAR (solo admin)
# ──────────────────────────────────────
@pedidos_bp.route('/<int:id>/editar-items', methods=['POST'])
@login_required
@admin_required
def editar_items_aprobado(id):
    """Editar precios/cantidades de una lista ya aprobada (sin tocar stock)."""
    lista = ListaPedido.query.get_or_404(id)
    cambios = 0
    actualizaciones = []
    for item in lista.items:
        if not item.producto_nombre.strip():
            continue
        sol_str   = request.form.get(f'sol_{item.id}', '').strip()
        rec_str   = request.form.get(f'rec_{item.id}', '').strip()
        precio_str= request.form.get(f'precio_{item.id}', '').strip()
        try:
            valores = {}
            if sol_str:
                valores['cantidad_solicitada'] = float(sol_str)
            if rec_str:
                valores['cantidad_recibida'] = float(rec_str)
            if precio_str:
                valores['precio_unitario'] = float(precio_str)
            if any(not math.isfinite(v) or v < 0 for v in valores.values()):
                raise ValueError
            actualizaciones.append((item, valores))
        except (TypeError, ValueError, OverflowError):
            db.session.rollback()
            flash('Las cantidades y precios deben ser numéricos, finitos y no negativos.', 'error')
            return redirect(url_for('pedidos.ver', id=id))
    for item, valores in actualizaciones:
        for campo, valor in valores.items():
            setattr(item, campo, valor)
        cambios += 1
    registrar_auditoria(current_user.id, 'EDITAR_ITEMS_APROBADO',
                        'listas_pedido', lista.id,
                        f'{cambios} ítems editados post-aprobación',
                        ip=request.remote_addr)
    db.session.commit()
    flash(f'Precios y cantidades actualizados ({cambios} ítems).', 'success')
    return redirect(url_for('pedidos.ver', id=id))


@pedidos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def eliminar(id):
    if not current_user.es_admin():
        flash('No tienes permisos para eliminar.', 'error')
        return redirect(url_for('pedidos.ver', id=id))
    lista = ListaPedido.query.get_or_404(id)
    db.session.delete(lista)
    registrar_auditoria(current_user.id, 'ELIMINAR_LISTA',
                        'listas_pedido', id, ip=request.remote_addr)
    db.session.commit()
    flash('Lista eliminada.', 'success')
    return redirect(url_for('pedidos.index'))



# ──────────────────────────────────────
#  NOTIFICACIONES
# ──────────────────────────────────────
# ──────────────────────────────────────
#  COMPROBANTES (boletas/facturas de la lista)
# ──────────────────────────────────────
@pedidos_bp.route('/<int:id>/comprobante', methods=['POST'])
@login_required
@permiso_required('pedidos')
def agregar_comprobante(id):
    lista = ListaPedido.query.get_or_404(id)
    archivo = guardar_comprobante(request.files.get('archivo'))
    try:
        monto = float(request.form.get('monto_total', 0) or 0)
        if monto < 0 or not math.isfinite(monto):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        flash('El monto del comprobante debe ser válido y no negativo.', 'error')
        return redirect(url_for('pedidos.ver', id=id))
    comp = ComprobantePedido(
        lista_id=lista.id,
        tipo=request.form.get('tipo', 'boleta'),
        numero=request.form.get('numero', '').strip(),
        proveedor_nombre=request.form.get('proveedor_nombre', '').strip(),
        monto_total=monto,
        archivo=archivo,
        notas=request.form.get('notas', '').strip(),
        usuario_id=current_user.id,
        creado_en=now_peru()
    )
    db.session.add(comp)
    db.session.flush()
    # Asignar items seleccionados a este comprobante
    for item in lista.items:
        if request.form.get(f'item_{item.id}') == 'on':
            item.comprobante_id = comp.id
    db.session.commit()
    flash(f'Comprobante agregado ({comp.tipo} #{comp.numero or "S/N"}).', 'success')
    return redirect(url_for('pedidos.ver', id=id))


@pedidos_bp.route('/comprobante/<int:cid>/eliminar', methods=['POST'])
@login_required
@permiso_required('pedidos')
def eliminar_comprobante(cid):
    comp = ComprobantePedido.query.get_or_404(cid)
    lista_id = comp.lista_id
    # Desasignar items
    for item in comp.items:
        item.comprobante_id = None
    db.session.delete(comp)
    db.session.commit()
    flash('Comprobante eliminado.', 'success')
    return redirect(url_for('pedidos.ver', id=lista_id))


@pedidos_bp.route('/comprobante/archivo/<filename>')
@login_required
@permiso_required('pedidos')
def comprobante_archivo(filename):
    safe_name = secure_filename(filename)
    private_folder = os.path.join(current_app.instance_path, UPLOAD_COMPROBANTES)
    legacy_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'comprobantes_pedido')
    folder = private_folder if os.path.isfile(os.path.join(private_folder, safe_name)) else legacy_folder
    return send_from_directory(folder, safe_name, as_attachment=True)


@pedidos_bp.route('/notificaciones')
@login_required
def notificaciones():
    from models import Reserva
    from datetime import date, timedelta
    hoy = now_peru().date()

    # Auto-generar alertas de reservas próximas (hoy y mañana)
    try:
        manana = hoy + timedelta(days=1)
        reservas_prox = Reserva.query.filter(
            Reserva.fecha.in_([hoy, manana]),
            Reserva.estado.in_(['pendiente', 'confirmada'])
        ).all() if current_user.rol in ('administrador', 'supervisor') or current_user.permisos.filter_by(permiso='reservas').first() else []
        for r in reservas_prox:
            existe = Notificacion.query.filter_by(
                destinatario_id=current_user.id,
                referencia_tipo='reserva',
                referencia_id=r.id,
                leido=False
            ).first()
            if not existe:
                cuando = 'HOY' if r.fecha == hoy else 'MAÑANA'
                db.session.add(Notificacion(
                    tipo='info',
                    titulo=f'Reserva {cuando}: {r.nombre_grupo or "Grupo"}',
                    mensaje=f'{r.num_pax or 0} pax · {r.hora or "sin hora"}',
                    referencia_id=r.id, referencia_tipo='reserva',
                    destinatario_id=current_user.id,
                    creado_por_id=current_user.id,
                    creado_en=now_peru()
                ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    mostrar = request.args.get('mostrar', 'pendientes')
    q = Notificacion.query.filter_by(destinatario_id=current_user.id)
    if mostrar == 'pendientes':
        q = q.filter_by(leido=False)
    notifs = q.order_by(Notificacion.creado_en.desc()).limit(100).all()

    return render_template('pedidos/notificaciones.html', notificaciones=notifs, mostrar=mostrar)


@pedidos_bp.route('/notificaciones/<int:id>/leer', methods=['POST'])
@login_required
def leer_notificacion(id):
    n = Notificacion.query.filter_by(id=id, destinatario_id=current_user.id).first_or_404()
    n.leido = True
    db.session.commit()
    return redirect(request.referrer or url_for('pedidos.notificaciones'))


@pedidos_bp.route('/notificaciones/leer-todas', methods=['POST'])
@login_required
def leer_todas_notificaciones():
    Notificacion.query.filter_by(
        destinatario_id=current_user.id, leido=False
    ).update({'leido': True})
    db.session.commit()
    flash('Todas las notificaciones marcadas como leídas.', 'success')
    return redirect(url_for('pedidos.notificaciones'))


@pedidos_bp.route('/notificaciones/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_notificacion(id):
    n = Notificacion.query.filter_by(id=id, destinatario_id=current_user.id).first_or_404()
    db.session.delete(n)
    db.session.commit()
    return redirect(url_for('pedidos.notificaciones'))
# ──────────────────────────────────────
#  IMPRIMIR / PDF (solo items con cantidad)
# ──────────────────────────────────────
@pedidos_bp.route('/<int:id>/imprimir')
@login_required
@permiso_required('pedidos')
def imprimir(id):
    lista = ListaPedido.query.get_or_404(id)
    # Solo items que tienen cantidad solicitada > 0 o al menos nombre + unidad
    items_imprimir = [
        i for i in lista.items
        if i.producto_nombre.strip() and (
            (i.cantidad_solicitada and i.cantidad_solicitada > 0)
        )
    ]
    from datetime import date as _date
    return render_template('pedidos/imprimir.html',
                           now_date=now_peru().date().strftime('%d/%m/%Y'),
                           lista=lista,
                           items_imprimir=items_imprimir)
