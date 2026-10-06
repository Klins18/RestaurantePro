from datetime import datetime

from models import db, KardexAlmacen, Producto, now_peru


def recalcular_producto(producto_id):
    """Recalcula cantidad y costo promedio del Kardex en orden cronológico."""
    registros = KardexAlmacen.query.filter_by(producto_id=producto_id).order_by(
        KardexAlmacen.fecha, KardexAlmacen.id
    ).all()
    cantidad = 0.0
    valor = 0.0
    for registro in registros:
        if registro.tipo == 'ingreso':
            precio = registro.precio_entrada or 0.0
            if not registro.costo_conocido:
                precio = valor / cantidad if cantidad > 0 else 0.0
                registro.precio_entrada = round(precio, 4)
                registro.total_entrada = round((registro.cant_entrada or 0) * precio, 2)
            cantidad += registro.cant_entrada or 0.0
            valor += registro.total_entrada or 0.0
        elif registro.tipo == 'egreso':
            precio = valor / cantidad if cantidad > 0 else 0.0
            registro.precio_salida = round(precio, 4)
            registro.total_salida = round((registro.cant_salida or 0) * precio, 2)
            cantidad -= registro.cant_salida or 0.0
            valor -= registro.total_salida
        registro.cant_saldo = round(cantidad, 4)
        registro.total_saldo = round(max(valor, 0.0), 2)
        registro.precio_saldo = round(valor / cantidad, 4) if cantidad > 0 else 0.0
    db.session.flush()
    return registros[-1] if registros else None


def registrar_kardex(producto_id, tipo, cantidad, usuario_id=None, concepto='',
                     referencia='', fecha=None, precio_unitario=None,
                     compra_id=None):
    """Añade un movimiento y conserva el costo promedio si la entrada no tiene precio."""
    cantidad = float(cantidad or 0)
    if cantidad <= 0:
        return None
    fecha_movimiento = fecha or now_peru()
    ultimo = KardexAlmacen.query.filter_by(producto_id=producto_id).order_by(
        KardexAlmacen.fecha.desc(), KardexAlmacen.id.desc()
    ).first()
    # No permitir que una fecha retroactiva deje el saldo final antes de un saldo inicial.
    if ultimo and fecha_movimiento < ultimo.fecha:
        fecha_movimiento = ultimo.fecha
    conocido = tipo != 'ingreso' or (precio_unitario is not None and float(precio_unitario) > 0)
    movimiento = KardexAlmacen(
        producto_id=producto_id,
        fecha=fecha_movimiento,
        tipo=tipo,
        concepto=concepto,
        referencia=referencia,
        cant_entrada=cantidad if tipo == 'ingreso' else 0,
        precio_entrada=float(precio_unitario or 0) if conocido and tipo == 'ingreso' else 0,
        total_entrada=round(cantidad * float(precio_unitario or 0), 2)
            if conocido and tipo == 'ingreso' else 0,
        cant_salida=cantidad if tipo == 'egreso' else 0,
        usuario_id=usuario_id,
        compra_id=compra_id,
        costo_conocido=conocido,
    )
    db.session.add(movimiento)
    db.session.flush()
    recalcular_producto(producto_id)
    return movimiento


def crear_saldos_iniciales():
    """Alinea el Kardex una sola vez con el stock real ya registrado en el sistema."""
    for producto in Producto.query.all():
        ultimo = KardexAlmacen.query.filter_by(producto_id=producto.id).order_by(
            KardexAlmacen.fecha.desc(), KardexAlmacen.id.desc()
        ).first()
        saldo_kardex = float(ultimo.cant_saldo or 0) if ultimo else 0.0
        saldo_real = float(producto.stock_actual or 0)
        diferencia = round(saldo_real - saldo_kardex, 4)
        if abs(diferencia) <= 0.0001:
            continue
        tipo = 'ingreso' if diferencia > 0 else 'egreso'
        registrar_kardex(
            producto.id, tipo, abs(diferencia),
            usuario_id=None,
            concepto='Saldo inicial al habilitar el Kardex' if not ultimo
                else 'Regularización inicial para conciliar el stock existente',
            referencia='SALDO-INICIAL' if not ultimo else 'CONCILIACION-INICIAL',
            precio_unitario=None,
        )
    db.session.commit()
