from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_required, current_user
from routes.decorators import admin_required, supervisor_required, permiso_required
from models import db, ListaPedido, ItemPedido, Usuario, Producto, MovimientoAlmacen, KardexAlmacen, Notificacion, registrar_auditoria
from datetime import datetime, date
import pytz

pedidos_bp = Blueprint('pedidos', __name__, url_prefix='/pedidos')
PERU_TZ = pytz.timezone('America/Lima')

def now_peru():
    return datetime.now(PERU_TZ).replace(tzinfo=None)

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

TIPOS_REQUERIMIENTO = list(LISTAS_PREDEFINIDAS.keys()) + ['LÁCTEOS Y DERIVADOS', 'BEBIDAS', 'OTROS']

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
    listas = q.all()
    return render_template('pedidos/index.html', listas=listas,
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
            fecha = date.today()

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

            try:
                cant = float(cantidades[i]) if i < len(cantidades) and cantidades[i].strip() else None
            except:
                cant = None

            # ── Solo guardar ítems CON cantidad pedida ──
            if not cant or cant <= 0:
                continue

            try:
                precio = float(precios[i]) if i < len(precios) and precios[i].strip() else None
            except:
                precio = None

            item = ItemPedido(
                lista_id=lista.id,
                producto_nombre=nombre,
                unidad_medida=unidades[i] if i < len(unidades) else '',
                cantidad_solicitada=cant,
                precio_unitario=precio,
                observacion=obs_items[i] if i < len(obs_items) else '',
                orden=orden
            )
            db.session.add(item)
            orden += 1

        registrar_auditoria(current_user.id, 'CREAR_LISTA_PEDIDO',
                            'listas_pedido', lista.id,
                            f'Lista: {lista.titulo}', ip=request.remote_addr)
        db.session.commit()
        flash('Lista de pedido creada.', 'success')
        return redirect(url_for('pedidos.ver', id=lista.id))

    return render_template('pedidos/nueva.html',
                           tipos=TIPOS_REQUERIMIENTO,
                           listas_predefinidas=LISTAS_PREDEFINIDAS,
                           hoy=date.today())

# ──────────────────────────────────────
#  API lista predefinida
# ──────────────────────────────────────
@pedidos_bp.route('/api/lista-predefinida/<tipo>')
@login_required
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
                item.cantidad_recibida = None
            # Si está marcado pero sin cantidad recibida → usar la cantidad solicitada
            if verificado and not item.cantidad_recibida and item.cantidad_solicitada:
                item.cantidad_recibida = item.cantidad_solicitada
            try:
                item.precio_unitario = float(precio_str) if precio_str else item.precio_unitario
            except:
                pass
            item.observacion = obs

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
                    prod = Producto.query.get(item.producto_id)
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
                    from sqlalchemy import text
                    cat_nombre = (lista.tipo_requerimiento or 'General').upper()

                    # INSERT OR IGNORE evita el UNIQUE constraint sin importar acentos
                    db.session.execute(
                        text("INSERT OR IGNORE INTO categorias (nombre, activo) VALUES (:n, 1)"),
                        {"n": cat_nombre}
                    )
                    db.session.flush()
                    # Ahora SELECT exacto — siempre existe
                    cat = Categoria.query.filter_by(nombre=cat_nombre).first()
                    # Fallback por si el nombre en BD difiere (ej: ya existía con otro case)
                    if not cat:
                        cat = Categoria.query.filter_by(activo=True).first()

                    unidad = item.unidad_medida or 'unid'
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
                    prod.stock_actual = (prod.stock_actual or 0) + item.cantidad_recibida
                    mov = MovimientoAlmacen(
                        tipo='ingreso',
                        producto_id=prod.id,
                        cantidad=item.cantidad_recibida,
                        motivo=f'Verificación pedido #{lista.id}: {lista.titulo}',
                        referencia=f'PEDIDO-{lista.id}',
                        usuario_id=current_user.id,
                        fecha_hora=now_peru()
                    )
                    db.session.add(mov)

                    precio_compra = item.precio_unitario or 0
                    if precio_compra > 0:
                        ultimo_k = KardexAlmacen.query.filter_by(producto_id=prod.id)\
                            .order_by(KardexAlmacen.id.desc()).first()
                        cant_prev  = ultimo_k.cant_saldo  if ultimo_k else 0
                        total_prev = ultimo_k.total_saldo if ultimo_k else 0
                        nueva_cant  = cant_prev + item.cantidad_recibida
                        nuevo_total = total_prev + (item.cantidad_recibida * precio_compra)
                        precio_prom = nuevo_total / nueva_cant if nueva_cant > 0 else precio_compra
                        k = KardexAlmacen(
                            producto_id=prod.id,
                            fecha=datetime.combine(lista.fecha, datetime.min.time()),
                            tipo='ingreso', concepto=f'Verificación pedido #{lista.id}',
                            referencia=f'PEDIDO-{lista.id}',
                            cant_entrada=item.cantidad_recibida, precio_entrada=precio_compra,
                            total_entrada=round(item.cantidad_recibida * precio_compra, 2),
                            cant_saldo=round(nueva_cant, 4), precio_saldo=round(precio_prom, 4),
                            total_saldo=round(nuevo_total, 2), usuario_id=current_user.id
                        )
                        db.session.add(k)

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
@permiso_required('pedidos')
def aprobar(id):
    # Empleados Y administradores pueden aprobar
    lista = ListaPedido.query.get_or_404(id)

    if lista.estado not in ('en_verificacion', 'completado', 'pendiente'):
        flash('Esta lista ya fue aprobada.', 'warning')
        return redirect(url_for('pedidos.ver', id=id))

    # Hacer update de stock para ítems verificados que aún no tuvieron movimiento
    items_actualizados = 0
    for item in lista.items:
        if item.verificado and item.cantidad_recibida and item.cantidad_recibida > 0:
            # Verificar si ya se hizo el movimiento durante la verificación
            mov_existente = MovimientoAlmacen.query.filter_by(
                referencia=f'PEDIDO-{lista.id}'
            ).filter(
                MovimientoAlmacen.motivo.contains(item.producto_nombre[:10])
            ).first()

            if not mov_existente:
                # Buscar producto y actualizar si no se hizo antes
                prod = None
                if item.producto_id:
                    prod = Producto.query.get(item.producto_id)
                if not prod:
                    prod = Producto.query.filter(
                        Producto.nombre.ilike(f'%{item.producto_nombre.strip()}%')
                    ).first()
                if prod:
                    prod.stock_actual = (prod.stock_actual or 0) + item.cantidad_recibida
                    mov = MovimientoAlmacen(
                        tipo='ingreso',
                        producto_id=prod.id,
                        cantidad=item.cantidad_recibida,
                        motivo=f'Aprobación pedido #{lista.id}: {lista.titulo}',
                        referencia=f'PEDIDO-{lista.id}',
                        usuario_id=current_user.id,
                        fecha_hora=now_peru()
                    )
                    db.session.add(mov)
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
@pedidos_bp.route('/notificaciones')
@login_required
def notificaciones():
    notifs = Notificacion.query.filter_by(
        destinatario_id=current_user.id
    ).order_by(Notificacion.creado_en.desc()).limit(50).all()
    # Marcar como leídas
    for n in notifs:
        n.leido = True
    db.session.commit()
    return render_template('pedidos/notificaciones.html', notificaciones=notifs)


@pedidos_bp.route('/notificaciones/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_notificacion(id):
    n = Notificacion.query.get_or_404(id)
    if n.destinatario_id == current_user.id:
        db.session.delete(n)
        db.session.commit()
    return redirect(url_for('pedidos.notificaciones'))
# ──────────────────────────────────────
#  IMPRIMIR / PDF (solo items con cantidad)
# ──────────────────────────────────────
@pedidos_bp.route('/<int:id>/imprimir')
@login_required
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
                           now_date=_date.today().strftime('%d/%m/%Y'),
                           lista=lista,
                           items_imprimir=items_imprimir)