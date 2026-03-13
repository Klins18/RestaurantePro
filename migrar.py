"""
SCRIPT DE MIGRACIÓN - RestoPro
Ejecutar UNA SOLA VEZ para actualizar la base de datos.

Uso:
    python migrar.py

Este script agrega las columnas nuevas que faltan en la base de datos existente
sin borrar ningún dato.
"""
import sqlite3
import os
import sys
import shutil
from datetime import datetime

# ─── Encontrar la base de datos ───
DB_PATH = None
posibles = [
    'restaurante.db',
    'instance/restaurante.db', 
    'data/restaurante.db',
    'db/restaurante.db',
]
for p in posibles:
    if os.path.exists(p):
        DB_PATH = p
        break

if not DB_PATH:
    # Buscar cualquier .db
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in ['venv', '__pycache__', '.git']]
        for f in files:
            if f.endswith('.db'):
                DB_PATH = os.path.join(root, f)
                break
        if DB_PATH:
            break

if not DB_PATH:
    print("❌ No se encontró la base de datos .db")
    print("   Especifica la ruta manualmente editando DB_PATH en este script.")
    sys.exit(1)

print(f"📁 Base de datos encontrada: {DB_PATH}")

# ─── Backup automático ───
backup = DB_PATH + f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
shutil.copy2(DB_PATH, backup)
print(f"💾 Backup creado: {backup}")

# ─── Migración ───
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

migraciones = []
errores = []

def columna_existe(tabla, columna):
    cur.execute(f"PRAGMA table_info({tabla})")
    return any(row[1] == columna for row in cur.fetchall())

def tabla_existe(tabla):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,))
    return cur.fetchone() is not None

# ════════════════════════════════════════════════
#  1. items_pedido.precio_unitario
# ════════════════════════════════════════════════
if tabla_existe('items_pedido'):
    if not columna_existe('items_pedido', 'precio_unitario'):
        try:
            cur.execute("ALTER TABLE items_pedido ADD COLUMN precio_unitario REAL")
            migraciones.append("✓ items_pedido.precio_unitario agregada")
        except Exception as e:
            errores.append(f"✗ items_pedido.precio_unitario: {e}")
    else:
        migraciones.append("· items_pedido.precio_unitario ya existe")
else:
    errores.append("✗ Tabla items_pedido no existe")

# ════════════════════════════════════════════════
#  2. Tablas nuevas de empleados
# ════════════════════════════════════════════════

if not tabla_existe('empleados'):
    try:
        cur.execute("""
        CREATE TABLE empleados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombres VARCHAR(100) NOT NULL,
            apellidos VARCHAR(100) NOT NULL,
            dni VARCHAR(20) UNIQUE,
            telefono VARCHAR(20),
            direccion VARCHAR(255),
            fecha_nacimiento DATE,
            tipo_sangre VARCHAR(5),
            cargo VARCHAR(100),
            fecha_ingreso DATE,
            tipo_contrato VARCHAR(20) DEFAULT 'fijo',
            sueldo_base REAL DEFAULT 0,
            activo BOOLEAN DEFAULT 1,
            usuario_id INTEGER REFERENCES usuarios(id)
        )
        """)
        migraciones.append("✓ Tabla empleados creada")
    except Exception as e:
        errores.append(f"✗ Tabla empleados: {e}")
else:
    # Verificar columnas que podrían faltar
    for col, tipo in [('tipo_sangre', 'VARCHAR(5)'), ('fecha_ingreso', 'DATE')]:
        if not columna_existe('empleados', col):
            try:
                cur.execute(f"ALTER TABLE empleados ADD COLUMN {col} {tipo}")
                migraciones.append(f"✓ empleados.{col} agregada")
            except Exception as e:
                errores.append(f"✗ empleados.{col}: {e}")
    migraciones.append("· Tabla empleados ya existe")

if not tabla_existe('asistencias'):
    try:
        cur.execute("""
        CREATE TABLE asistencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER NOT NULL REFERENCES empleados(id),
            fecha DATE NOT NULL,
            estado VARCHAR(20) DEFAULT 'presente',
            hora_entrada VARCHAR(10),
            hora_salida VARCHAR(10),
            horas_extra REAL DEFAULT 0,
            descuento REAL DEFAULT 0,
            observacion VARCHAR(255),
            registrado_por INTEGER REFERENCES usuarios(id),
            creado_en DATETIME,
            UNIQUE(empleado_id, fecha)
        )
        """)
        migraciones.append("✓ Tabla asistencias creada")
    except Exception as e:
        errores.append(f"✗ Tabla asistencias: {e}")
else:
    migraciones.append("· Tabla asistencias ya existe")

if not tabla_existe('funciones_diarias'):
    try:
        cur.execute("""
        CREATE TABLE funciones_diarias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER NOT NULL REFERENCES empleados(id),
            fecha DATE NOT NULL,
            funcion VARCHAR(200) NOT NULL,
            area VARCHAR(50),
            completado BOOLEAN DEFAULT 0,
            observacion VARCHAR(255),
            registrado_por INTEGER REFERENCES usuarios(id),
            creado_en DATETIME
        )
        """)
        migraciones.append("✓ Tabla funciones_diarias creada")
    except Exception as e:
        errores.append(f"✗ Tabla funciones_diarias: {e}")
else:
    migraciones.append("· Tabla funciones_diarias ya existe")

# ════════════════════════════════════════════════
#  3. Otras columnas que podrían faltar
# ════════════════════════════════════════════════

# KardexAlmacen - por si acaso
if tabla_existe('kardex_almacen'):
    for col, tipo in [('precio_promedio', 'REAL'), ('valor_total', 'REAL')]:
        if not columna_existe('kardex_almacen', col):
            try:
                cur.execute(f"ALTER TABLE kardex_almacen ADD COLUMN {col} {tipo}")
                migraciones.append(f"✓ kardex_almacen.{col} agregada")
            except Exception as e:
                pass  # No crítico

# ════════════════════════════════════════════════
#  4. Tabla notificaciones
# ════════════════════════════════════════════════
if not tabla_existe('notificaciones'):
    try:
        cur.execute("""
        CREATE TABLE notificaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo VARCHAR(30) DEFAULT 'info',
            titulo VARCHAR(200) NOT NULL,
            mensaje TEXT,
            referencia_id INTEGER,
            referencia_tipo VARCHAR(30),
            destinatario_id INTEGER REFERENCES usuarios(id),
            leido BOOLEAN DEFAULT 0,
            creado_en DATETIME,
            creado_por_id INTEGER REFERENCES usuarios(id)
        )
        """)
        migraciones.append("✓ Tabla notificaciones creada")
    except Exception as e:
        errores.append(f"✗ Tabla notificaciones: {e}")
else:
    migraciones.append("· Tabla notificaciones ya existe")

conn.commit()
conn.close()

# ─── Reporte ───
print("\n" + "═"*50)
print("  RESULTADO DE LA MIGRACIÓN")
print("═"*50)
for m in migraciones:
    print(" ", m)

if errores:
    print("\nERRORES:")
    for e in errores:
        print(" ", e)
    print("\n⚠️  Hubo errores. Revisa los mensajes arriba.")
else:
    print("\n✅ Migración completada exitosamente.")
    print("   Ahora puedes reiniciar el servidor Flask.")
print("═"*50)

# ── Registro de Pasajeros, Balones de Gas y Reservas ──
for sql, nombre in [
    ("""CREATE TABLE IF NOT EXISTS registro_pasajeros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha DATE NOT NULL,
        empresa_id INTEGER,
        nombre_grupo VARCHAR(120),
        num_pax INTEGER DEFAULT 0,
        precio_buffet FLOAT DEFAULT 0,
        ruta VARCHAR(120),
        observaciones VARCHAR(255),
        creado_en DATETIME,
        usuario_id INTEGER,
        FOREIGN KEY(empresa_id) REFERENCES empresas_turisticas(id))""", "registro_pasajeros"),
    ("""CREATE TABLE IF NOT EXISTS balones_gas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_compra DATE NOT NULL,
        fecha_inicio DATE,
        fecha_fin DATE,
        proveedor VARCHAR(120),
        precio FLOAT DEFAULT 0,
        peso_kg FLOAT DEFAULT 10,
        estado VARCHAR(20) DEFAULT 'disponible',
        observaciones VARCHAR(255),
        dias_uso INTEGER,
        creado_en DATETIME,
        usuario_id INTEGER)""", "balones_gas"),
    ("""CREATE TABLE IF NOT EXISTS reservas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha DATE NOT NULL,
        hora VARCHAR(5),
        nombre_grupo VARCHAR(150),
        num_pax INTEGER DEFAULT 0,
        precio_buffet FLOAT DEFAULT 0,
        empresa_id INTEGER,
        observaciones TEXT,
        estado VARCHAR(20) DEFAULT 'pendiente',
        alerta_vista BOOLEAN DEFAULT 0,
        creado_en DATETIME,
        usuario_id INTEGER,
        FOREIGN KEY(empresa_id) REFERENCES empresas_turisticas(id))""", "reservas"),
]:
    try:
        cursor.execute(sql); conn.commit()
        migraciones.append(f"+ tabla {nombre}")
    except Exception as e:
        if "already exists" not in str(e).lower(): errores.append(f"{nombre}: {e}")

# ── Auditoría Asistencia, Cierre Asistencia y Honorarios ──
for sql, nombre in [
    ("""CREATE TABLE IF NOT EXISTS auditoria_asistencia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asistencia_id INTEGER NOT NULL,
        empleado_id INTEGER NOT NULL,
        campo_cambiado VARCHAR(50),
        valor_anterior VARCHAR(100),
        valor_nuevo VARCHAR(100),
        justificacion VARCHAR(255) NOT NULL,
        usuario_id INTEGER,
        fecha_hora DATETIME,
        FOREIGN KEY(asistencia_id) REFERENCES asistencias(id),
        FOREIGN KEY(empleado_id) REFERENCES empleados(id))""", "auditoria_asistencia"),
    ("""CREATE TABLE IF NOT EXISTS cierres_asistencia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha DATE NOT NULL UNIQUE,
        cerrado_por INTEGER,
        cerrado_en DATETIME)""", "cierres_asistencia"),
    ("""CREATE TABLE IF NOT EXISTS honorarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        empleado_id INTEGER NOT NULL,
        fecha_pago DATE NOT NULL,
        periodo_desde DATE,
        periodo_hasta DATE,
        monto FLOAT NOT NULL,
        tipo_pago VARCHAR(30) DEFAULT 'efectivo',
        concepto VARCHAR(200),
        numero_recibo VARCHAR(50),
        archivo_recibo VARCHAR(255),
        estado VARCHAR(20) DEFAULT 'pagado',
        observaciones TEXT,
        usuario_id INTEGER,
        creado_en DATETIME,
        FOREIGN KEY(empleado_id) REFERENCES empleados(id))""", "honorarios"),
]:
    try:
        cursor.execute(sql); conn.commit()
        migraciones.append(f"+ tabla {nombre}")
    except Exception as e:
        if "already exists" not in str(e).lower(): errores.append(f"{nombre}: {e}")

# ── Permisos individuales por usuario ──
try:
    cursor.execute("""CREATE TABLE IF NOT EXISTS permisos_usuario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        permiso VARCHAR(50) NOT NULL,
        otorgado_por INTEGER,
        otorgado_en DATETIME,
        UNIQUE(usuario_id, permiso),
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id))""")
    conn.commit()
    migraciones.append("+ tabla permisos_usuario")
except Exception as e:
    if "already exists" not in str(e).lower(): errores.append(f"permisos_usuario: {e}")
