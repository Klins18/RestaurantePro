import math
import re
import secrets
from datetime import datetime, time

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from models import (
    IngredienteProduccion,
    IngredienteReceta,
    MovimientoAlmacen,
    Producto,
    ProduccionCocina,
    Receta,
    db,
    now_peru,
    registrar_auditoria,
)
from routes.decorators import admin_required, permiso_required
from services.kardex import registrar_kardex
from services.units import INVENTORY_UNIT_CHOICES, convert_quantity, normalize_unit, unit_label


cocina_bp = Blueprint('cocina', __name__, url_prefix='/cocina')
CATEGORIAS_RECETA = ('Sopa', 'Entrada', 'Fondo', 'Postre', 'Bebida', 'Otro')
UNIDADES_RENDIMIENTO = ('porciones', 'tandas', 'litros', 'jarras', 'vasos', 'unidades', 'fuentes')
TIPOS_CONSUMO = {
    'personal': 'Consumo personal',
    'propietario': 'Consumo de propietario',
    'cocina': 'Uso interno de cocina',
}
TOKEN_RE = re.compile(r'^[0-9a-f]{32}$')


def _parse_fecha(raw):
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return now_peru().date()


def _cantidad_positiva(raw):
    try:
        cantidad = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Ingresa una cantidad numérica válida.')
    if not math.isfinite(cantidad) or cantidad <= 0:
        raise ValueError('La cantidad debe ser mayor que cero.')
    return cantidad


def _redirect_fecha(fecha):
    return redirect(url_for('cocina.index', fecha=fecha.isoformat()))


@cocina_bp.route('/')
@login_required
@permiso_required('cocina')
def index():
    fecha = _parse_fecha(request.args.get('fecha'))
    recetas = Receta.query.filter_by(activa=True).options(
        selectinload(Receta.ingredientes).joinedload(IngredienteReceta.producto)
    ).order_by(Receta.categoria, Receta.nombre).all()
    producciones = ProduccionCocina.query.filter_by(fecha_preparacion=fecha).options(
        joinedload(ProduccionCocina.receta),
        joinedload(ProduccionCocina.usuario),
        selectinload(ProduccionCocina.consumos),
    ).order_by(ProduccionCocina.creado_en.desc(), ProduccionCocina.id.desc()).all()

    inicio = datetime.combine(fecha, time.min)
    fin = datetime.combine(fecha, time.max)
    consumos_internos = MovimientoAlmacen.query.filter(
        MovimientoAlmacen.referencia.like('CONSUMO-INT-%'),
        MovimientoAlmacen.fecha_hora >= inicio,
        MovimientoAlmacen.fecha_hora <= fin,
    ).options(joinedload(MovimientoAlmacen.producto), joinedload(MovimientoAlmacen.usuario)).order_by(
        MovimientoAlmacen.fecha_hora.desc(), MovimientoAlmacen.id.desc()
    ).limit(50).all()

    from models import VentaDiaria
    pasajeros = db.session.query(db.func.coalesce(db.func.sum(VentaDiaria.num_pax), 0)).filter(
        VentaDiaria.fecha == fecha
    ).scalar()
    productos = Producto.query.filter_by(activo=True).outerjoin(
        Producto.categoria
    ).order_by(Producto.categoria_id, Producto.nombre).all()
    token_consumo = secrets.token_hex(16)
    tokens_produccion = {receta.id: secrets.token_hex(16) for receta in recetas}
    return render_template(
        'cocina/index.html', fecha=fecha, recetas=recetas,
        producciones=producciones, consumos_internos=consumos_internos,
        productos=productos, pasajeros=int(pasajeros or 0),
        token_consumo=token_consumo, tokens_produccion=tokens_produccion,
        hoy=now_peru().date(),
        tipos_consumo=TIPOS_CONSUMO,
        unidad_label=unit_label,
    )


@cocina_bp.route('/recetas')
@login_required
@admin_required
def recetas():
    recetas_lista = Receta.query.options(
        selectinload(Receta.ingredientes).joinedload(IngredienteReceta.producto)
    ).order_by(Receta.activa.desc(), Receta.categoria, Receta.nombre).all()
    receta_id = request.args.get('editar', type=int)
    receta_editar = db.session.get(Receta, receta_id) if receta_id else None
    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    unidades = list(INVENTORY_UNIT_CHOICES)
    valores_unidad = {item['value'] for item in unidades}
    for producto in productos:
        unidad = normalize_unit(producto.unidad_medida)
        if unidad and unidad not in valores_unidad:
            unidades.append({'value': unidad, 'label': unit_label(unidad)})
            valores_unidad.add(unidad)
    return render_template(
        'cocina/recetas.html', recetas=recetas_lista,
        receta_editar=receta_editar, productos=productos,
        categorias=CATEGORIAS_RECETA,
        unidades_rendimiento=UNIDADES_RENDIMIENTO,
        unidades=unidades,
        unidad_label=unit_label,
    )


@cocina_bp.route('/recetas/guardar', methods=['POST'])
@login_required
@admin_required
def guardar_receta():
    nombre = request.form.get('nombre', '').strip()
    categoria = request.form.get('categoria', 'Otro').strip()
    unidad_rendimiento = normalize_unit(request.form.get('unidad_rendimiento', 'porciones'))
    receta_id = request.form.get('receta_id', type=int)
    try:
        rendimiento = _cantidad_positiva(request.form.get('rendimiento'))
        margen_pct = float(request.form.get('margen_pct', '15'))
        if not nombre or len(nombre) > 150:
            raise ValueError('El nombre debe tener entre 1 y 150 caracteres.')
        if categoria not in CATEGORIAS_RECETA:
            raise ValueError('Selecciona una categoría válida.')
        if unidad_rendimiento not in UNIDADES_RENDIMIENTO:
            raise ValueError('Selecciona una unidad de rendimiento válida.')
        if not math.isfinite(margen_pct) or not 0 <= margen_pct <= 50:
            raise ValueError('El margen de referencia debe estar entre 0 % y 50 %.')

        producto_ids = request.form.getlist('producto_id')
        cantidades = request.form.getlist('cantidad')
        unidades = request.form.getlist('unidad_medida')
        if not producto_ids or len(producto_ids) != len(cantidades) or len(producto_ids) != len(unidades):
            raise ValueError('Agrega al menos un ingrediente completo a la receta.')
        if len(producto_ids) > 50:
            raise ValueError('Una receta no puede tener más de 50 ingredientes.')

        ingredientes_nuevos = []
        productos_vistos = set()
        for raw_id, raw_cantidad, raw_unidad in zip(producto_ids, cantidades, unidades):
            producto = db.session.get(Producto, int(raw_id))
            cantidad = _cantidad_positiva(raw_cantidad)
            unidad = normalize_unit(raw_unidad)
            if not producto or not producto.activo:
                raise ValueError('Uno de los ingredientes ya no está activo en almacén.')
            if producto.id in productos_vistos:
                raise ValueError(f'{producto.nombre} aparece más de una vez. Deja una sola línea por producto.')
            productos_vistos.add(producto.id)
            convert_quantity(cantidad, unidad, producto.unidad_medida)
            ingredientes_nuevos.append((producto, cantidad, unidad))
        duplicada = Receta.query.filter(
            db.func.lower(db.func.trim(Receta.nombre)) == nombre.casefold()
        )
        if receta_id:
            duplicada = duplicada.filter(Receta.id != receta_id)
        if duplicada.first():
            raise ValueError('Ya existe una receta con ese nombre.')
    except (TypeError, ValueError, OverflowError) as error:
        db.session.rollback()
        flash(str(error), 'error')
        return redirect(url_for('cocina.recetas', editar=receta_id) if receta_id else url_for('cocina.recetas'))

    receta = db.session.get(Receta, receta_id) if receta_id else None
    if receta_id and not receta:
        flash('No se encontró la receta que intentas editar.', 'error')
        return redirect(url_for('cocina.recetas'))
    if receta is None:
        receta = Receta(creado_por_id=current_user.id)
        db.session.add(receta)
        accion = 'CREAR_RECETA_COCINA'
    else:
        receta.ingredientes.clear()
        accion = 'EDITAR_RECETA_COCINA'

    receta.nombre = nombre
    receta.categoria = categoria
    receta.rendimiento = rendimiento
    receta.unidad_rendimiento = unidad_rendimiento
    receta.margen_pct = margen_pct
    receta.activa = True
    db.session.flush()
    for producto, cantidad, unidad in ingredientes_nuevos:
        receta.ingredientes.append(IngredienteReceta(
            producto_id=producto.id,
            cantidad=cantidad,
            unidad_medida=unidad,
        ))
    registrar_auditoria(
        current_user.id, accion, 'recetas_cocina', receta.id,
        f'{receta.nombre} | rendimiento: {rendimiento} {unidad_rendimiento}',
        ip=request.remote_addr,
    )
    db.session.commit()
    flash(f'Receta "{nombre}" guardada.', 'success')
    return redirect(url_for('cocina.recetas'))


@cocina_bp.route('/recetas/<int:receta_id>/estado', methods=['POST'])
@login_required
@admin_required
def cambiar_estado_receta(receta_id):
    receta = db.get_or_404(Receta, receta_id)
    receta.activa = not receta.activa
    registrar_auditoria(
        current_user.id, 'ACTIVAR_RECETA_COCINA' if receta.activa else 'DESACTIVAR_RECETA_COCINA',
        'recetas_cocina', receta.id, receta.nombre, ip=request.remote_addr,
    )
    db.session.commit()
    flash(f'Receta "{receta.nombre}" {"activada" if receta.activa else "desactivada"}.', 'success')
    return redirect(url_for('cocina.recetas'))


@cocina_bp.route('/produccion', methods=['POST'])
@login_required
@permiso_required('cocina')
def registrar_produccion():
    fecha = _parse_fecha(request.form.get('fecha_preparacion'))
    if fecha > now_peru().date():
        flash('Registra la preparación el día que realmente se elaboren los alimentos.', 'error')
        return _redirect_fecha(fecha)
    token = request.form.get('token', '').strip().lower()
    if not TOKEN_RE.fullmatch(token):
        flash('No se pudo validar el envío. Recarga la página e inténtalo de nuevo.', 'error')
        return _redirect_fecha(fecha)
    if ProduccionCocina.query.filter_by(token=token).first():
        flash('Esta producción ya se registró; no se descontó dos veces.', 'info')
        return _redirect_fecha(fecha)

    receta = db.session.get(Receta, request.form.get('receta_id', type=int))
    if not receta or not receta.activa:
        flash('Selecciona una receta activa.', 'error')
        return _redirect_fecha(fecha)
    try:
        cantidad_producida = _cantidad_positiva(request.form.get('cantidad_producida'))
        if cantidad_producida > 100000:
            raise ValueError('La cantidad producida excede el límite permitido.')
        necesidades = {}
        productos = {}
        detalle_consumo = []
        for ingrediente in receta.ingredientes:
            producto = ingrediente.producto
            if not producto or not producto.activo:
                raise ValueError('La receta incluye un ingrediente inactivo o inexistente.')
            estimada_receta = ingrediente.cantidad * cantidad_producida / receta.rendimiento
            cantidad_real_receta = _cantidad_positiva(request.form.get(
                f'cantidad_real_{ingrediente.id}', str(estimada_receta),
            ))
            estimada = round(convert_quantity(
                estimada_receta, ingrediente.unidad_medida, producto.unidad_medida,
            ), 4)
            cantidad = round(convert_quantity(
                cantidad_real_receta, ingrediente.unidad_medida, producto.unidad_medida,
            ), 4)
            if not math.isfinite(cantidad) or cantidad <= 0 or not math.isfinite(estimada) or estimada <= 0:
                raise ValueError(f'La cantidad calculada para {producto.nombre} es demasiado pequeña.')
            necesidades[producto.id] = necesidades.get(producto.id, 0.0) + cantidad
            productos[producto.id] = producto
            diferencia_pct = abs(cantidad_real_receta - estimada_receta) / estimada_receta * 100
            detalle_consumo.append((ingrediente, producto, estimada, cantidad, diferencia_pct > receta.margen_pct))
    except (TypeError, ValueError, OverflowError) as error:
        db.session.rollback()
        flash(str(error), 'error')
        return _redirect_fecha(fecha)

    nuevo = ProduccionCocina(
        receta_id=receta.id,
        fecha_preparacion=fecha,
        cantidad_producida=cantidad_producida,
        unidad_rendimiento=receta.unidad_rendimiento,
        token=token,
        usuario_id=current_user.id,
        nota=request.form.get('nota', '').strip()[:255] or None,
    )
    db.session.add(nuevo)
    try:
        db.session.flush()
        movimientos_por_producto = []
        for producto_id, cantidad in sorted(necesidades.items()):
            resultado = db.session.execute(
                update(Producto)
                .where(Producto.id == producto_id, Producto.activo.is_(True), Producto.stock_actual >= cantidad)
                .values(stock_actual=Producto.stock_actual - cantidad)
                .execution_options(synchronize_session=False)
            )
            if resultado.rowcount != 1:
                db.session.rollback()
                disponible = float(productos[producto_id].stock_actual or 0)
                flash(
                    f'Stock insuficiente de {productos[producto_id].nombre}. '
                    f'Disponible: {disponible:g} {unit_label(productos[producto_id].unidad_medida)}; '
                    f'necesitas: {cantidad:g}. No se registró ninguna producción.',
                    'error',
                )
                return _redirect_fecha(fecha)
            movimientos_por_producto.append((productos[producto_id], cantidad))

        fecha_movimiento = now_peru()
        referencia_base = f'COCINA-PROD-{nuevo.id}'
        for producto, cantidad in movimientos_por_producto:
            unidad = normalize_unit(producto.unidad_medida)
            referencia = f'{referencia_base}-{producto.id}'
            concepto = (
                f'Producción cocina: {receta.nombre} '
                f'({cantidad_producida:g} {receta.unidad_rendimiento}; preparación {fecha.isoformat()})'
            )
            db.session.add(MovimientoAlmacen(
                tipo='egreso', producto_id=producto.id, cantidad=cantidad,
                unidad_medida=unidad, motivo=concepto, referencia=referencia,
                usuario_id=current_user.id, fecha_hora=fecha_movimiento,
            ))
            registrar_kardex(
                producto.id, 'egreso', cantidad, current_user.id,
                concepto=concepto, referencia=referencia, fecha=fecha_movimiento,
            )
        for _ingrediente, producto, estimada, cantidad, fuera_margen in detalle_consumo:
            nuevo.consumos.append(IngredienteProduccion(
                producto_id=producto.id,
                producto_nombre=producto.nombre,
                cantidad_estimada=estimada,
                cantidad=cantidad,
                unidad_medida=normalize_unit(producto.unidad_medida),
                fuera_margen=fuera_margen,
            ))
        desviaciones = [
            f'{producto.nombre}: previsto {estimada:g}, real {cantidad:g} {unit_label(producto.unidad_medida)}'
            for _ingrediente, producto, estimada, cantidad, fuera_margen in detalle_consumo
            if fuera_margen
        ]
        registrar_auditoria(
            current_user.id, 'PRODUCCION_COCINA', 'producciones_cocina', nuevo.id,
            f'{receta.nombre} | {cantidad_producida:g} {receta.unidad_rendimiento} | preparación {fecha.isoformat()}',
            ip=request.remote_addr,
        )
        if desviaciones:
            registrar_auditoria(
                current_user.id, 'AJUSTE_RECETA_COCINA', 'producciones_cocina', nuevo.id,
                'Consumos fuera del margen de referencia: ' + '; '.join(desviaciones),
                ip=request.remote_addr,
            )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if ProduccionCocina.query.filter_by(token=token).first():
            flash('Esta producción ya se registró; no se descontó dos veces.', 'info')
            return _redirect_fecha(fecha)
        flash('No se pudo registrar la producción. Revisa el inventario e inténtalo de nuevo.', 'error')
        return _redirect_fecha(fecha)
    except Exception:
        db.session.rollback()
        raise

    flash(f'Preparación de "{receta.nombre}" registrada. Se descontaron las cantidades reales del almacén.', 'success')
    return _redirect_fecha(fecha)


@cocina_bp.route('/consumo-interno', methods=['POST'])
@login_required
@permiso_required('cocina')
def registrar_consumo_interno():
    fecha = _parse_fecha(request.form.get('fecha_preparacion'))
    if fecha != now_peru().date():
        flash('El consumo interno se registra el día que ocurre. Selecciona “Hoy” para continuar.', 'error')
        return _redirect_fecha(fecha)
    token = request.form.get('token', '').strip().lower()
    if not TOKEN_RE.fullmatch(token):
        flash('No se pudo validar el envío. Recarga la página e inténtalo de nuevo.', 'error')
        return _redirect_fecha(fecha)
    referencia = f'CONSUMO-INT-{token}'
    if MovimientoAlmacen.query.filter_by(referencia=referencia).first():
        flash('Este consumo interno ya se registró; no se descontó dos veces.', 'info')
        return _redirect_fecha(fecha)

    try:
        producto_id = int(request.form.get('producto_id', ''))
        producto = db.session.get(Producto, producto_id)
        cantidad = _cantidad_positiva(request.form.get('cantidad'))
        tipo = request.form.get('tipo_consumo', '')
        if not producto or not producto.activo:
            raise ValueError('Selecciona un producto activo del almacén.')
        if tipo not in TIPOS_CONSUMO:
            raise ValueError('Selecciona un tipo de consumo válido.')
        persona = request.form.get('persona', '').strip()[:120]
        nota = request.form.get('nota', '').strip()[:255]
        if cantidad > 100000:
            raise ValueError('La cantidad excede el límite permitido.')
    except (TypeError, ValueError, OverflowError) as error:
        db.session.rollback()
        flash(str(error) or 'Revisa los datos del consumo.', 'error')
        return _redirect_fecha(fecha)

    resultado = db.session.execute(
        update(Producto)
        .where(Producto.id == producto.id, Producto.activo.is_(True), Producto.stock_actual >= cantidad)
        .values(stock_actual=Producto.stock_actual - cantidad)
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount != 1:
        db.session.rollback()
        stock_actual = float(producto.stock_actual or 0)
        flash(
            f'Stock insuficiente de {producto.nombre}. Disponible: {stock_actual:g} '
            f'{unit_label(producto.unidad_medida)}. No se registró el consumo.',
            'error',
        )
        return _redirect_fecha(fecha)

    unidad = normalize_unit(producto.unidad_medida)
    descripcion = TIPOS_CONSUMO[tipo]
    observaciones = ' | '.join(texto for texto in (
        f'Registrado como: {persona}' if persona else '', nota,
    ) if texto) or None
    fecha_movimiento = now_peru()
    db.session.add(MovimientoAlmacen(
        tipo='egreso', producto_id=producto.id, cantidad=cantidad,
        unidad_medida=unidad, motivo=descripcion, referencia=referencia,
        usuario_id=current_user.id, fecha_hora=fecha_movimiento,
        observaciones=observaciones,
    ))
    registrar_kardex(
        producto.id, 'egreso', cantidad, current_user.id,
        concepto=descripcion, referencia=referencia, fecha=fecha_movimiento,
    )
    registrar_auditoria(
        current_user.id, 'CONSUMO_INTERNO', 'movimientos_almacen', None,
        f'{producto.nombre} | -{cantidad:g} {unit_label(unidad)} | {descripcion}'
        + (f' | {persona}' if persona else '')
        + (f' | {nota}' if nota else ''),
        ip=request.remote_addr,
    )
    db.session.commit()
    flash(f'Consumo interno de {producto.nombre} registrado. No se generó una venta.', 'success')
    return _redirect_fecha(fecha)
