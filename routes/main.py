from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from models import db, Producto, ListaPedido, MovimientoAlmacen, VentaDiaria
from sqlalchemy import func
from datetime import date, timedelta
import pytz

main_bp = Blueprint('main', __name__)
PERU_TZ = pytz.timezone('America/Lima')

@main_bp.route('/')
@login_required
def dashboard():
    hoy = date.today()

    # Métricas principales
    total_productos    = Producto.query.filter_by(activo=True).count()
    pedidos_pendientes = ListaPedido.query.filter_by(estado='pendiente').count()
    pedidos_verificacion = ListaPedido.query.filter_by(estado='en_verificacion').count()
    productos_bajos    = Producto.query.filter(
        Producto.activo == True,
        Producto.stock_actual <= Producto.stock_minimo,
        Producto.stock_minimo > 0
    ).count()

    # Ventas de hoy
    ventas_hoy_list  = VentaDiaria.query.filter_by(fecha=hoy).all()
    ventas_hoy       = sum(v.total or 0 for v in ventas_hoy_list)
    pax_hoy          = sum(v.num_pax or 0 for v in ventas_hoy_list)
    num_servicios_hoy = len(ventas_hoy_list)

    # Ventas ayer para comparar
    ayer = hoy - timedelta(days=1)
    ventas_ayer = sum(v.total or 0 for v in VentaDiaria.query.filter_by(fecha=ayer).all())
    variacion_ventas = ((ventas_hoy - ventas_ayer) / ventas_ayer * 100) if ventas_ayer > 0 else 0

    # Serie últimos 7 días para mini-gráfico
    serie_7dias = []
    for i in range(6, -1, -1):
        d = hoy - timedelta(days=i)
        total_dia = sum(v.total or 0 for v in VentaDiaria.query.filter_by(fecha=d).all())
        serie_7dias.append({'fecha': d.strftime('%d/%m'), 'total': round(total_dia, 2)})

    # Últimos movimientos
    ultimos_movimientos = MovimientoAlmacen.query.order_by(
        MovimientoAlmacen.fecha_hora.desc()
    ).limit(6).all()

    # Últimas listas
    ultimas_listas = ListaPedido.query.order_by(
        ListaPedido.elaborado_en.desc()
    ).limit(5).all()

    # Cierre de hoy
    from models import CierreCaja
    cierre_hoy = CierreCaja.query.filter_by(fecha=hoy).first()

    # ── Funciones del día para el usuario logueado ──
    mis_funciones = []
    from models import Empleado, FuncionDiaria
    empleado_actual = Empleado.query.filter_by(
        usuario_id=current_user.id, activo=True
    ).first()
    if empleado_actual:
        mis_funciones = FuncionDiaria.query.filter_by(
            empleado_id=empleado_actual.id, fecha=hoy
        ).order_by(FuncionDiaria.completado, FuncionDiaria.id).all()

    # Reservas de hoy y mañana (alertas)
    from models import Reserva
    manana = hoy + timedelta(days=1)
    reservas_proximas = Reserva.query.filter(
        Reserva.fecha.in_([hoy, manana]),
        Reserva.estado.in_(['pendiente', 'confirmada'])
    ).order_by(Reserva.fecha, Reserva.hora).all()

    return render_template('dashboard.html',
        total_productos=total_productos,
        pedidos_pendientes=pedidos_pendientes,
        pedidos_verificacion=pedidos_verificacion,
        alertas_stock=productos_bajos,
        ventas_hoy=ventas_hoy,
        pax_hoy=pax_hoy,
        num_servicios_hoy=num_servicios_hoy,
        ventas_ayer=ventas_ayer,
        variacion_ventas=round(variacion_ventas, 1),
        serie_7dias=serie_7dias,
        ultimos_movimientos=ultimos_movimientos,
        ultimas_listas=ultimas_listas,
        cierre_hoy=cierre_hoy,
        mis_funciones=mis_funciones,
        empleado_actual=empleado_actual,
        reservas_proximas=reservas_proximas,
        hoy=hoy,
    )


@main_bp.route('/funcion/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_funcion_dashboard(id):
    """Marcar/desmarcar función directamente desde el dashboard."""
    from models import FuncionDiaria, Empleado
    f = FuncionDiaria.query.get_or_404(id)
    # Solo puede tocar sus propias funciones
    emp = Empleado.query.filter_by(usuario_id=current_user.id).first()
    if emp and f.empleado_id == emp.id:
        f.completado = not f.completado
        db.session.commit()
    return redirect(url_for('main.dashboard'))