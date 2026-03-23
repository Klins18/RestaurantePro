"""
Ejecutar desde D:\RestaurantePro\ con:
  python agregar_columnas_reservas.py
"""
import sqlite3, os

db_path = 'restaurante_pro.db'
if not os.path.exists(db_path):
    print(f"ERROR: no se encontró {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

columnas = [
    "ALTER TABLE reservas ADD COLUMN monto_anticipado REAL DEFAULT 0",
    "ALTER TABLE reservas ADD COLUMN saldo_pendiente  REAL DEFAULT 0",
    "ALTER TABLE reservas ADD COLUMN tipo_pago        VARCHAR(30)",
    "ALTER TABLE reservas ADD COLUMN estado_pago      VARCHAR(20) DEFAULT 'sin_pago'",
    "ALTER TABLE reservas ADD COLUMN archivo_voucher  VARCHAR(255)",
]

for sql in columnas:
    col = sql.split("ADD COLUMN")[1].strip().split()[0]
    try:
        cursor.execute(sql)
        conn.commit()
        print(f"  ✓ columna '{col}' agregada")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print(f"  · columna '{col}' ya existe (ok)")
        else:
            print(f"  ✗ ERROR en '{col}': {e}")

conn.close()
print("\n✅ Listo. Reinicia el servidor.")