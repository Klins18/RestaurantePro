from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Bien, KardexBienes, CategoriaBien, registrar_auditoria
from datetime import date, datetime
import pytz

bienes_bp = Blueprint('bienes', __name__, url_prefix='/bienes')
PERU_TZ = pytz.timezone('America/Lima')

AREAS = ['ALMACÉN', 'COMEDOR', 'COCINA']

# Datos iniciales del inventario físico
SEED_BIENES = [
    # (area, categoria, nombre, bueno, malo, total, obs)
    # ─── ALMACÉN ───
    ("ALMACÉN","Mobiliario",      "Estantes de metal",                    0,0,4,""),
    ("ALMACÉN","Mobiliario",      "Estantes de plástico",                 0,0,3,""),
    ("ALMACÉN","Mobiliario",      "Estantes de metal (Verduras)",         0,0,3,""),
    ("ALMACÉN","Equipos",         "Balanza",                              0,0,1,""),
    ("ALMACÉN","Equipos",         "Conservadora",                         0,0,1,""),
    ("ALMACÉN","Equipos",         "Congeladora",                          0,0,1,""),
    ("ALMACÉN","Equipos",         "Licuadora",                            0,0,2,""),
    ("ALMACÉN","Equipos",         "Exprimidor de naranja",                0,0,1,""),
    ("ALMACÉN","Utensilios",      "Termos",                               2,4,6,""),
    ("ALMACÉN","Utensilios",      "Dispensador de aceites",               0,1,2,""),
    ("ALMACÉN","Utensilios",      "Vaso de licuadora",                    1,1,2,""),
    ("ALMACÉN","Utensilios",      "Samombali",                            0,0,1,""),
    ("ALMACÉN","Utensilios",      "Dispensador de aceite (tipo jarra)",   0,0,6,"4+2"),
    ("ALMACÉN","Utensilios",      "Sartén cuadrada",                      0,1,1,""),
    ("ALMACÉN","Utensilios",      "Cuchilla de licuadora",                0,0,1,""),
    ("ALMACÉN","Utensilios",      "Tabla para picar",                     0,0,1,""),
    ("ALMACÉN","Utensilios",      "Termos de comedor",                    0,0,6,""),
    ("ALMACÉN","Otros",           "Colgadores de fierro",                 0,2,2,""),
    ("ALMACÉN","Otros",           "Tachos de plástico",                   0,0,4,""),
    ("ALMACÉN","Otros",           "Baldes de plástico",                   0,0,15,""),
    ("ALMACÉN","Otros",           "Tapers de plástico grandes",           0,0,3,""),
    ("ALMACÉN","Otros",           "Tapers de plástico pequeños",          0,0,3,""),
    ("ALMACÉN","Otros",           "Canostas",                             0,0,10,""),
    # ─── COMEDOR ───
    ("COMEDOR","Cubertería",      "Tenedores",                            295,41,336,""),
    ("COMEDOR","Cubertería",      "Cucharas",                             329,46,375,""),
    ("COMEDOR","Cubertería",      "Cuchillos de mesa",                    290,41,331,""),
    ("COMEDOR","Cubertería",      "Cucharillas",                          143,25,168,""),
    ("COMEDOR","Cubertería",      "Saleros",                              0,0,113,"10+47+56"),
    ("COMEDOR","Cubertería",      "Pinza grande",                         0,0,14,"2+3+3+6"),
    ("COMEDOR","Cubertería",      "Pinza pequeñas",                       0,0,5,""),
    ("COMEDOR","Cubertería",      "Cucharones",                           18,13,31,"6+7"),
    ("COMEDOR","Cubertería",      "Cuchara para crema",                   0,0,5,"3+1+1"),
    ("COMEDOR","Cubertería",      "Cucharitas de café",                   0,0,10,""),
    ("COMEDOR","Menajería",       "Platos de vidrio - postres",           0,0,120,"46+11"),
    ("COMEDOR","Menajería",       "Tazas de té",                          0,5,99,"17+54+28"),
    ("COMEDOR","Menajería",       "Platos de ñoñera - postres",           0,0,38,""),
    ("COMEDOR","Menajería",       "Vasos de mesa - mediano",              0,0,140,"14+80+6+40"),
    ("COMEDOR","Menajería",       "Platos de ensaladas",                  0,0,67,"47+20"),
    ("COMEDOR","Menajería",       "Platillos de té",                      0,0,106,"31+43+19+2+11"),
    ("COMEDOR","Menajería",       "Platos planos",                        0,20,292,"76+189+27 - retirado 4"),
    ("COMEDOR","Menajería",       "Platos de sopa",                       0,4,163,"97+6+60 - retirado 1"),
    ("COMEDOR","Menajería",       "Platos soperos hondos",                0,2,9,"8+1"),
    ("COMEDOR","Menajería",       "Cucharas de entrada loza",             0,0,37,"21+16"),
    ("COMEDOR","Menajería",       "Postrero caracol (bowl)",              0,0,13,"11+2"),
    ("COMEDOR","Menajería",       "Bowl circular - postres loza",         0,0,6,"4+1+1"),
    ("COMEDOR","Menajería",       "Fuente de ensalada con orejas",        5,2,7,""),
    ("COMEDOR","Menajería",       "Fuentes de torte",                     0,0,4,"3+1"),
    ("COMEDOR","Menajería",       "Bowls de cremas",                      0,1,7,"3+2+2"),
    ("COMEDOR","Menajería",       "Fuentes de wanton grandes",            0,0,3,"2+1"),
    ("COMEDOR","Menajería",       "Fuentes de wanton mediano",            2,0,2,""),
    ("COMEDOR","Menajería",       "Fuentes de wanton pequeño",            2,0,2,""),
    ("COMEDOR","Menajería",       "Fuente rectangular de ensalada",       0,0,4,"2+2"),
    ("COMEDOR","Menajería",       "Pontoneros de loza",                   24,0,24,""),
    ("COMEDOR","Menajería",       "Bowl circular para ensalada",          1,0,1,""),
    ("COMEDOR","Menajería",       "Bowl cuadrado - postre",               4,0,4,""),
    ("COMEDOR","Menajería",       "Bowl circular de loza - grande",       1,0,1,""),
    ("COMEDOR","Menajería",       "Platos planos grandes",                30,0,30,""),
    ("COMEDOR","Menajería",       "Taza de café expreso",                 12,0,12,""),
    ("COMEDOR","Menajería",       "Taza café americano",                  12,0,12,""),
    ("COMEDOR","Menajería",       "Taza de capuchino",                    11,0,11,""),
    ("COMEDOR","Menajería",       "Platillos de café",                    12,0,12,""),
    ("COMEDOR","Menajería",       "Lecheritas de loza",                   6,0,6,""),
    ("COMEDOR","Cristalería",     "Pirex circular",                       3,0,3,""),
    ("COMEDOR","Cristalería",     "Pirex ovalado",                        0,0,3,"2+1"),
    ("COMEDOR","Cristalería",     "Pirex rectangular",                    6,1,7,""),
    ("COMEDOR","Cristalería",     "Pirex ovalado pequeño",                1,0,1,""),
    ("COMEDOR","Cristalería",     "Fuente de loza ovalada",               1,0,1,""),
    ("COMEDOR","Cristalería",     "Samovar circular",                     0,0,19,"6+6+1+6"),
    ("COMEDOR","Cristalería",     "Samovar rectangular",                  0,0,3,"2+1"),
    ("COMEDOR","Cristalería",     "Samovar ovalado",                      0,0,4,"1+2+1"),
    ("COMEDOR","Cristalería",     "Vasos medianos - mesa",                0,0,47,"25+22"),
    ("COMEDOR","Cristalería",     "Vasos largos para jugo",               0,0,31,"24+6+1"),
    ("COMEDOR","Cristalería",     "Vasos largos grandes - limonada",      0,0,20,"10+4+4+2"),
    ("COMEDOR","Cristalería",     "Jarros de vidrio con asa",             0,1,3,"2+1"),
    ("COMEDOR","Cristalería",     "Jarros forma botella",                 0,1,8,"5+1+2"),
    ("COMEDOR","Cristalería",     "Lechero de vidrio",                    1,0,1,""),
    ("COMEDOR","Cristalería",     "Copas",                                15,0,15,""),
    ("COMEDOR","Cristalería",     "Copa tipo planta",                     3,0,3,""),
    ("COMEDOR","Cristalería",     "Vaso para whiski",                     0,0,9,"6+3"),
    ("COMEDOR","Cristalería",     "Copas pequeñas",                       0,0,77,"20+57"),
    ("COMEDOR","Cristalería",     "Vasitos para shots",                   6,0,6,""),
    ("COMEDOR","Cristalería",     "Vaso para cóctel",                     12,0,12,""),
    ("COMEDOR","Mantelería",      "Manteles blancos largos (grandes)",    0,2,42,"23+16+3"),
    ("COMEDOR","Mantelería",      "Manteles blancos pequeños",            0,0,10,"5+5"),
    ("COMEDOR","Mantelería",      "Caminos azules grandes",               0,0,31,"13+15+3"),
    ("COMEDOR","Mantelería",      "Caminos azules pequeños",              6,0,6,""),
    ("COMEDOR","Mantelería",      "Caminos negros",                       0,0,30,"2+17+3+8"),
    ("COMEDOR","Mantelería",      "Mantas rojas grandes",                 9,6,15,""),
    ("COMEDOR","Mantelería",      "Caminos manta roja grande",            0,0,9,"5+4"),
    ("COMEDOR","Mantelería",      "Caminos manta roja pequeño",           7,0,7,""),
    ("COMEDOR","Mantelería",      "Manteles rojos pequeños",              4,3,7,""),
    ("COMEDOR","Mantelería",      "Manteles amarillos grandes",           0,5,28,"15+2+11"),
    ("COMEDOR","Mantelería",      "Manteles amarillos pequeños",          7,0,7,""),
    ("COMEDOR","Mantelería",      "Secadores rojos",                      6,0,6,""),
    ("COMEDOR","Mantelería",      "Secadores amarillos",                  0,0,20,"11+7+2"),
    ("COMEDOR","Mantelería",      "Secadores amarillos pequeños",         2,0,2,""),
    ("COMEDOR","Mantelería",      "Secadores naranjas pequeños",          6,0,6,""),
    ("COMEDOR","Mantelería",      "Faldones amarillos",                   10,0,10,""),
    ("COMEDOR","Otros",           "Porta cucharillas",                    0,0,2,"1+1"),
    ("COMEDOR","Otros",           "Porta coca",                           0,0,3,"1+2"),
    ("COMEDOR","Otros",           "Recipiente de picadillo",              1,0,1,""),
    ("COMEDOR","Otros",           "Thermos",                              3,0,3,""),
    ("COMEDOR","Otros",           "Azucarero",                            0,0,2,"1+1"),
    ("COMEDOR","Otros",           "Bandeja rectangular",                  40,0,40,""),
    ("COMEDOR","Otros",           "Dispensador aceite (whopper)",         4,0,4,""),
    # ─── COCINA ───
    ("COCINA","Equipos",          "Cocina",                               0,0,2,""),
    ("COCINA","Equipos",          "Calentadora grande",                   0,0,2,""),
    ("COCINA","Equipos",          "Calentadora pequeña",                  0,0,2,""),
    ("COCINA","Equipos",          "Exprimidor",                           0,0,1,""),
    ("COCINA","Equipos",          "Licuadora",                            0,0,2,""),
    ("COCINA","Equipos",          "Exprimidor de naranja",                0,0,1,""),
    ("COCINA","Mobiliario",       "Mesa de trabajo",                      0,0,3,""),
    ("COCINA","Utensilios",       "Sartenes",                             9,2,11,""),
    ("COCINA","Utensilios",       "Olla grande",                          0,0,4,""),
    ("COCINA","Utensilios",       "Olla mediana",                         0,0,20,""),
    ("COCINA","Utensilios",       "Olla a presión",                       6,2,8,""),
    ("COCINA","Utensilios",       "Escurridor",                           0,0,3,""),
    ("COCINA","Utensilios",       "Bol aluminio mediano",                 0,0,15,""),
    ("COCINA","Utensilios",       "Bol aluminio grande",                  0,0,6,""),
    ("COCINA","Utensilios",       "Cuchillo",                             0,0,16,""),
    ("COCINA","Utensilios",       "Machete",                              1,1,2,""),
    ("COCINA","Utensilios",       "Cortador de papa",                     0,0,1,""),
    ("COCINA","Utensilios",       "Cucharón de madera",                   0,0,8,""),
    ("COCINA","Utensilios",       "Cucharón de plástico",                 0,0,4,""),
    ("COCINA","Utensilios",       "Espumadera",                           0,0,7,""),
    ("COCINA","Utensilios",       "Cucharón grande",                      0,0,2,""),
    ("COCINA","Utensilios",       "Pisapapas",                            0,0,1,""),
    ("COCINA","Utensilios",       "Ralladora",                            0,0,2,""),
    ("COCINA","Utensilios",       "Pelapapas",                            0,0,3,""),
    ("COCINA","Utensilios",       "Tabla para picar",                     0,0,9,""),
    ("COCINA","Utensilios",       "Tasas",                                0,0,4,""),
    ("COCINA","Utensilios",       "Vasos de plástico",                    0,0,4,""),
    ("COCINA","Utensilios",       "Cesta para freidora",                  0,0,6,""),
    ("COCINA","Utensilios",       "Colador de plástico",                  4,2,6,""),
    ("COCINA","Utensilios",       "Colador de acero",                     0,0,10,""),
    ("COCINA","Utensilios",       "Tapas medianas",                       0,0,5,""),
    ("COCINA","Utensilios",       "Asadera",                              0,0,1,""),
    ("COCINA","Utensilios",       "Tapa de olla presión",                 3,3,6,""),
    ("COCINA","Utensilios",       "Tapas grandes",                        0,0,2,""),
    ("COCINA","Utensilios",       "Jarras",                               0,0,2,""),
    ("COCINA","Utensilios",       "Colador de plástico grande",           0,0,1,""),
    ("COCINA","Utensilios",       "Escorridor de platos",                 0,0,1,""),
    ("COCINA","Otros",            "Bandera",                              0,0,8,""),
    ("COCINA","Otros",            "Balde mediano",                        0,0,2,""),
    ("COCINA","Otros",            "Balde grande",                         0,0,1,""),
    ("COCINA","Otros",            "Canasta de pan",                       0,0,2,""),
]

CAT_COLORS = {
    "Cubertería":  "#dbeafe", "Menajería":  "#dcfce7",
    "Cristalería": "#e0e7ff", "Mantelería": "#fef3c7",
    "Mobiliario":  "#f3e8ff", "Equipos":    "#fce7f3",
    "Utensilios":  "#fef9c3", "Otros":      "#f1f5f9",
}


def registrar_kardex_bien(bien, tipo, bueno_antes=0, malo_antes=0,
                          total_antes=0, costo_antes=None, motivo='',
                          usuario_id=None, fecha=None, saldo_bueno=None,
                          saldo_malo=None, saldo_total=None):
    bueno_despues = int(bien.estado_bueno or 0) if saldo_bueno is None else saldo_bueno
    malo_despues = int(bien.estado_malo or 0) if saldo_malo is None else saldo_malo
    total_despues = int(bien.total or 0) if saldo_total is None else saldo_total
    valor_antes = total_antes * costo_antes if costo_antes is not None else None
    valor_despues = total_despues * bien.costo_unitario if bien.costo_unitario is not None else None
    if valor_despues is None:
        valor_ajuste = None
    elif valor_antes is None:
        valor_ajuste = valor_despues
    else:
        valor_ajuste = round(valor_despues - valor_antes, 2)
    db.session.add(KardexBienes(
        bien_id=bien.id,
        bien_nombre=bien.nombre,
        fecha=fecha or datetime.now(PERU_TZ).replace(tzinfo=None),
        tipo=tipo,
        motivo=motivo,
        bueno_entrada=max(bueno_despues - bueno_antes, 0),
        bueno_salida=max(bueno_antes - bueno_despues, 0),
        malo_entrada=max(malo_despues - malo_antes, 0),
        malo_salida=max(malo_antes - malo_despues, 0),
        saldo_bueno=bueno_despues,
        saldo_malo=malo_despues,
        saldo_total=total_despues,
        costo_unitario=bien.costo_unitario,
        valor_ajuste=valor_ajuste,
        valor_saldo=round(valor_despues, 2) if valor_despues is not None else None,
        usuario_id=usuario_id,
    ))

# ─── SEMILLA automática ────────────────────────────────────────────────────
def seed_bienes():
    if Bien.query.count() == 0:
        hoy = date.today()
        cats_cache = {}
        for area, cat_nombre, nombre, bueno, malo, total, obs in SEED_BIENES:
            key = f"{area}|{cat_nombre}"
            if key not in cats_cache:
                cat = CategoriaBien.query.filter_by(nombre=cat_nombre, area=area).first()
                if not cat:
                    cat = CategoriaBien(nombre=cat_nombre, area=area)
                    db.session.add(cat)
                    db.session.flush()
                cats_cache[key] = cat
            cat = cats_cache[key]
            db.session.add(Bien(
                categoria_id=cat.id, nombre=nombre, area=area,
                estado_bueno=bueno, estado_malo=malo, total=total,
                observaciones=obs, fecha_registro=hoy,
            ))
        db.session.flush()

    # Los bienes existentes reciben un saldo de apertura al habilitar este Kardex.
    bienes = Bien.query.filter_by(activo=True).all()
    for bien in bienes:
        if not KardexBienes.query.filter_by(bien_id=bien.id).first():
            registrar_kardex_bien(
                bien, 'saldo_inicial', bueno_antes=0, malo_antes=0, total_antes=0,
                motivo='Saldo al habilitar el Kardex de bienes',
                usuario_id=bien.usuario_id,
            )
    db.session.commit()


# ─── RUTAS ────────────────────────────────────────────────────────────────────

@bienes_bp.route('/')
@login_required
def index():
    area_sel  = request.args.get('area', '')
    cat_sel   = request.args.get('categoria', '')
    buscar    = request.args.get('q', '').strip()

    cats = CategoriaBien.query.filter_by(activo=True).order_by(CategoriaBien.area, CategoriaBien.nombre).all()

    q = Bien.query.filter_by(activo=True)
    if area_sel:  q = q.filter_by(area=area_sel)
    if cat_sel:   q = q.filter_by(categoria_id=int(cat_sel))
    if buscar:    q = q.filter(Bien.nombre.ilike(f'%{buscar}%'))
    bienes = q.order_by(Bien.area, Bien.categoria_id, Bien.nombre).all()

    # Resumen por área
    resumen = {}
    for a in AREAS:
        total_items = Bien.query.filter_by(area=a, activo=True).count()
        total_unid  = db.session.query(db.func.sum(Bien.total)).filter_by(area=a, activo=True).scalar() or 0
        total_malo  = db.session.query(db.func.sum(Bien.estado_malo)).filter_by(area=a, activo=True).scalar() or 0
        resumen[a] = {'items': total_items, 'unidades': total_unid, 'malo': total_malo}

    return render_template('bienes/index.html',
        bienes=bienes, cats=cats, areas=AREAS,
        area_sel=area_sel, cat_sel=cat_sel, buscar=buscar,
        resumen=resumen, cat_colors=CAT_COLORS)


@bienes_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo():
    if request.method == 'POST':
        cat_id  = request.form.get('categoria_id')
        nombre  = request.form.get('nombre', '').strip()
        area    = request.form.get('area', '')
        bueno   = int(request.form.get('estado_bueno', 0) or 0)
        malo    = int(request.form.get('estado_malo', 0) or 0)
        total   = int(request.form.get('total', 0) or 0) or (bueno + malo)
        obs     = request.form.get('observaciones', '').strip()
        costo_raw = request.form.get('costo_unitario', '').strip()
        try:
            costo_unitario = float(costo_raw) if costo_raw else None
            if costo_unitario is not None and costo_unitario < 0:
                raise ValueError
        except ValueError:
            flash('El costo unitario debe ser un monto igual o mayor que cero.', 'error')
            return redirect(request.url)

        if not nombre or not cat_id:
            flash('Nombre y categoría son obligatorios.', 'error')
        else:
            b = Bien(categoria_id=cat_id, nombre=nombre, area=area,
                     estado_bueno=bueno, estado_malo=malo, total=total,
                     costo_unitario=costo_unitario,
                     observaciones=obs, fecha_registro=date.today(),
                     usuario_id=current_user.id)
            db.session.add(b)
            db.session.flush()
            registrar_kardex_bien(
                b, 'ingreso', motivo='Alta inicial en inventario',
                usuario_id=current_user.id,
            )
            db.session.commit()
            flash(f'"{nombre}" agregado al inventario.', 'success')
            return redirect(url_for('bienes.index', area=area))

    cats = CategoriaBien.query.filter_by(activo=True).order_by(CategoriaBien.area, CategoriaBien.nombre).all()
    area_pre = request.args.get('area', '')
    return render_template('bienes/form.html', bien=None, cats=cats, areas=AREAS, area_pre=area_pre)


@bienes_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar(id):
    bien = Bien.query.get_or_404(id)
    if request.method == 'POST':
        bueno_antes = int(bien.estado_bueno or 0)
        malo_antes = int(bien.estado_malo or 0)
        total_antes = int(bien.total or 0)
        costo_antes = bien.costo_unitario
        costo_raw = request.form.get('costo_unitario', '').strip()
        try:
            costo_nuevo = float(costo_raw) if costo_raw else costo_antes
            if costo_nuevo is not None and costo_nuevo < 0:
                raise ValueError
        except ValueError:
            flash('El costo unitario debe ser un monto igual o mayor que cero.', 'error')
            return redirect(request.url)

        bien.categoria_id  = request.form.get('categoria_id')
        bien.nombre        = request.form.get('nombre', '').strip()
        bien.area          = request.form.get('area', '')
        bien.estado_bueno  = int(request.form.get('estado_bueno', 0) or 0)
        bien.estado_malo   = int(request.form.get('estado_malo', 0) or 0)
        bien.total         = int(request.form.get('total', 0) or 0)
        bien.observaciones = request.form.get('observaciones', '').strip()
        bien.costo_unitario = costo_nuevo
        cambio_cantidad = (
            bueno_antes != bien.estado_bueno or malo_antes != bien.estado_malo
            or total_antes != bien.total
        )
        cambio_costo = costo_antes != bien.costo_unitario
        if cambio_cantidad or cambio_costo:
            tipo_movimiento = 'ajuste' if cambio_cantidad else 'regularizacion_costo'
            motivo = request.form.get('motivo_kardex', '').strip()
            if not motivo:
                motivo = 'Costo actualizado' if cambio_costo and not cambio_cantidad else 'Ajuste desde edición del inventario'
            registrar_kardex_bien(
                bien, tipo_movimiento,
                bueno_antes=bueno_antes, malo_antes=malo_antes,
                total_antes=total_antes, costo_antes=costo_antes,
                motivo=motivo, usuario_id=current_user.id,
            )
        db.session.commit()
        flash('Bien actualizado.', 'success')
        return redirect(url_for('bienes.index', area=bien.area))

    cats = CategoriaBien.query.filter_by(activo=True).order_by(CategoriaBien.area, CategoriaBien.nombre).all()
    return render_template('bienes/form.html', bien=bien, cats=cats, areas=AREAS, area_pre=bien.area)


@bienes_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar(id):
    bien = Bien.query.get_or_404(id)
    registrar_kardex_bien(
        bien, 'baja',
        bueno_antes=int(bien.estado_bueno or 0),
        malo_antes=int(bien.estado_malo or 0),
        total_antes=int(bien.total or 0),
        costo_antes=bien.costo_unitario,
        motivo='Baja del inventario', usuario_id=current_user.id,
        saldo_bueno=0, saldo_malo=0, saldo_total=0,
    )
    bien.activo = False
    db.session.commit()
    flash(f'"{bien.nombre}" eliminado.', 'success')
    return redirect(url_for('bienes.index'))


@bienes_bp.route('/categorias', methods=['GET', 'POST'])
@login_required
def categorias():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        area   = request.form.get('area', '')
        desc   = request.form.get('descripcion', '').strip()
        if nombre and area:
            if not CategoriaBien.query.filter_by(nombre=nombre, area=area).first():
                db.session.add(CategoriaBien(nombre=nombre, area=area, descripcion=desc))
                db.session.commit()
                flash(f'Categoría "{nombre}" creada.', 'success')
            else:
                flash('Ya existe esa categoría en esa área.', 'error')
        return redirect(url_for('bienes.categorias'))

    cats = CategoriaBien.query.filter_by(activo=True).order_by(CategoriaBien.area, CategoriaBien.nombre).all()
    return render_template('bienes/categorias.html', cats=cats, areas=AREAS)


@bienes_bp.route('/categorias/<int:id>/editar', methods=['POST'])
@login_required
def editar_categoria(id):
    cat = CategoriaBien.query.get_or_404(id)
    cat.nombre = request.form.get('nombre', cat.nombre).strip()
    cat.descripcion = request.form.get('descripcion', '').strip()
    db.session.commit()
    flash('Categoría actualizada.', 'success')
    return redirect(url_for('bienes.categorias'))


@bienes_bp.route('/categorias/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_categoria(id):
    cat = CategoriaBien.query.get_or_404(id)
    if cat.bienes:
        flash(f'No se puede eliminar: tiene {len(cat.bienes)} bien(es) asignados.', 'error')
    else:
        db.session.delete(cat)
        db.session.commit()
        flash('Categoría eliminada.', 'success')
    return redirect(url_for('bienes.categorias'))
