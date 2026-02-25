from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from models import db, Producto, ListaPedido, MovimientoAlmacen, Auditoria
from sqlalchemy import func
from datetime import date, timedelta

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    # Estadísticas rápidas
    total_productos = Producto.query.filter_by(activo=True).count()
    pedidos_pendientes = ListaPedido.query.filter_by(estado='pendiente').count()
    pedidos_verificacion = ListaPedido.query.filter_by(estado='en_verificacion').count()

    # Productos con stock bajo
    productos_bajos = Producto.query.filter(
        Producto.activo == True,
        Producto.stock_actual <= Producto.stock_minimo,
        Producto.stock_minimo > 0
    ).count()

    # Últimos movimientos
    ultimos_movimientos = MovimientoAlmacen.query.order_by(
        MovimientoAlmacen.fecha_hora.desc()
    ).limit(8).all()

    # Últimas listas
    ultimas_listas = ListaPedido.query.order_by(
        ListaPedido.elaborado_en.desc()
    ).limit(5).all()

    # Ventas de hoy
    from models import VentaDiaria
    from datetime import date
    import pytz
    hoy = date.today()
    ventas_hoy_list = VentaDiaria.query.filter_by(fecha=hoy).all()
    ventas_hoy = sum(v.total or 0 for v in ventas_hoy_list)

    return render_template('dashboard.html',
        total_productos=total_productos,
        pedidos_pendientes=pedidos_pendientes,
        pedidos_verificacion=pedidos_verificacion,
        alertas_stock=productos_bajos,
        ventas_hoy=ventas_hoy,
        ultimos_movimientos=ultimos_movimientos,
        ultimas_listas=ultimas_listas
    )
