# 🍽️ RESTOPRO - Sistema de Gestión de Almacén
## Restaurante Turístico Marangani · 2026

Sistema offline completo para gestión de almacén, listas de pedido y control de inventario.  
Funciona a través de red WiFi local (router), sin necesidad de internet.

---

## 📁 ESTRUCTURA DEL PROYECTO

```
restaurante_pro/
│
├── app.py                          # ⭐ Aplicación principal (EJECUTAR ESTE)
├── config.py                       # Configuraciones generales
├── models.py                       # Modelos de base de datos (SQLite)
├── requirements.txt                # Dependencias Python
├── .env                            # Variables de entorno (crear desde .env.example)
├── .env.example                    # Plantilla de configuración
│
├── routes/                         # Rutas / Controladores
│   ├── __init__.py
│   ├── auth.py                     # Login y logout
│   ├── main.py                     # Dashboard principal
│   ├── pedidos.py                  # Listas de pedido y verificación
│   ├── almacen.py                  # Ingresos, egresos, movimientos
│   └── admin.py                    # Usuarios, productos, categorías, auditoría
│
├── templates/                      # Plantillas HTML
│   ├── base.html                   # Plantilla base (sidebar, header)
│   ├── login.html                  # Pantalla de inicio de sesión
│   ├── dashboard.html              # Dashboard con resumen
│   │
│   ├── pedidos/
│   │   ├── index.html              # Lista de todos los pedidos
│   │   ├── nueva.html              # Crear nueva lista (formulario dinámico)
│   │   ├── ver.html                # Ver detalle (formato como las fotos)
│   │   └── verificar.html          # Verificación con checkboxes
│   │
│   ├── almacen/
│   │   ├── index.html              # Inventario / Stock actual
│   │   ├── ingreso.html            # Registrar entrada de producto
│   │   ├── egreso.html             # Registrar salida de producto
│   │   └── movimientos.html        # Historial con filtros
│   │
│   └── admin/
│       ├── index.html              # Panel de administración
│       ├── usuarios.html           # Gestión de usuarios y roles
│       ├── categorias.html         # Categorías de productos
│       ├── productos.html          # Catálogo de productos
│       ├── proveedores.html        # Registro de proveedores
│       └── auditoria.html          # Log de todas las acciones
│
├── static/
│   ├── libs/                       # Librerías JS (descargar una vez con internet)
│   │   ├── tailwind.min.js         # Estilos CSS
│   │   └── chart.umd.min.js        # Gráficos (para reportes futuros)
│   ├── js/                         # JavaScript adicional
│   ├── css/                        # CSS adicional
│   └── uploads/                    # Archivos subidos (comprobantes, etc.)
│
├── backups/                        # Backups automáticos de la BD
│   └── restaurante_pro_YYYYMMDD_HHMMSS.db
│
└── restaurante_pro.db              # Base de datos SQLite (se crea al iniciar)
```

---

## 🚀 INSTALACIÓN PASO A PASO

### Requisitos Previos
- Python 3.8 o superior
- Windows, Linux o macOS
- ~150 MB de espacio en disco

---

### Paso 1: Descargar librerías JavaScript (CON INTERNET - solo una vez)

```bash
mkdir -p static/libs

# Tailwind CSS
curl -o static/libs/tailwind.min.js https://cdn.tailwindcss.com

# Chart.js
curl -o static/libs/chart.umd.min.js https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js
```

**Alternativa manual:**
1. Abrir https://cdn.tailwindcss.com → Guardar como `static/libs/tailwind.min.js`
2. Abrir https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js → Guardar como `static/libs/chart.umd.min.js`

---

### Paso 2: Crear entorno virtual

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / Mac
python3 -m venv venv
source venv/bin/activate
```

---

### Paso 3: Instalar dependencias

```bash
pip install -r requirements.txt
```

---

### Paso 4: Configurar variables de entorno

```bash
# Windows
copy .env.example .env

# Linux / Mac
cp .env.example .env
```

Editar `.env`:
```bash
FLASK_ENV=development
SECRET_KEY=clave-secreta-unica-cambiar-esto-12345
ADMIN_USERNAME=admin
ADMIN_PASSWORD=TuPasswordSegura2026!
RESTAURANTE_NOMBRE=Rest. Tco. Marangani
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
```

---

### Paso 5: Iniciar el sistema

```bash
python app.py
```

Al iniciar por primera vez:
- Se crea la base de datos automáticamente
- Se crea el usuario administrador
- Se crean las categorías por defecto (Verduras, Carnes, Abarrotes, etc.)
- Se crea un backup inicial

---

## 📡 ACCESO DESDE DISPOSITIVOS EN LA RED

1. El servidor muestra su IP al iniciar (ej: `192.168.1.100`)
2. Conecta todos los dispositivos al mismo router WiFi
3. Desde cualquier dispositivo, abrir el navegador:
   ```
   http://192.168.1.100:5000
   ```
4. Iniciar sesión con tu usuario y contraseña

**Cómo encontrar la IP del servidor:**
```bash
# Windows
ipconfig

# Linux / Mac
ifconfig
# o
ip addr
```

---

## 👥 ROLES Y PERMISOS

| Función | Administrador | Empleado |
|---------|:---:|:---:|
| Ver dashboard | ✅ | ✅ |
| Ver inventario | ✅ | ✅ |
| Registrar ingresos/egresos | ✅ | ✅ |
| Crear listas de pedido | ✅ | ✅ |
| Verificar listas (Check) | ✅ | ✅ |
| Aprobar listas | ✅ | ❌ |
| Eliminar listas | ✅ | ❌ |
| Gestionar usuarios | ✅ | ❌ |
| Gestionar productos | ✅ | ❌ |
| Ver auditoría completa | ✅ | ❌ |

---

## 📋 FLUJO DE TRABAJO (LISTAS DE PEDIDO)

```
1. EMPLEADO crea la lista de pedido
   └── Ingresa productos, cantidades y unidades
   
2. Se envía a compras → Estado: PENDIENTE ⏳

3. EMPLEADO o ADMIN verifica al recibir los productos
   └── Marca Check ✓ en cada producto recibido
   └── Ingresa cantidad real recibida
   └── Estado: EN VERIFICACIÓN 🔍 / COMPLETADO ✅

4. ADMINISTRADOR aprueba la lista
   └── Estado: APROBADO 🎯
```

Cada acción registra:
- ¿Quién lo hizo? (nombre completo)
- ¿Cuándo? (fecha y hora en hora Perú)
- ¿Desde qué dispositivo? (IP)

---

## 🔧 MANTENIMIENTO

### Backups automáticos
El sistema crea backups automáticamente al iniciar, guardados en `backups/`.
Se mantienen los últimos **10 backups**.

### Backup manual
```bash
# Windows
copy restaurante_pro.db backups\backup_manual.db

# Linux
cp restaurante_pro.db backups/backup_manual_$(date +%Y%m%d).db
```

### Restaurar backup
```bash
# 1. Detener el sistema (Ctrl+C)
# 2. Copiar backup como base de datos principal:
copy backups\restaurante_pro_FECHA.db restaurante_pro.db
# 3. Reiniciar:
python app.py
```

---

## 🐛 SOLUCIÓN DE PROBLEMAS

**El sistema no inicia:**
```bash
# Verificar que Python está instalado
python --version

# Verificar dependencias
pip install -r requirements.txt

# Verificar que el puerto no esté en uso
netstat -an | findstr 5000  # Windows
```

**No se puede acceder desde otros dispositivos:**
1. Verificar que `FLASK_HOST=0.0.0.0` en el archivo `.env`
2. Verificar firewall: permitir puerto 5000
3. Confirmar que todos están en la misma red WiFi

**Contraseña olvidada del admin:**
```bash
# Opción 1: Restaurar backup
# Opción 2: Resetear (SE PIERDEN TODOS LOS DATOS)
del restaurante_pro.db   # Windows
rm restaurante_pro.db    # Linux
python app.py
```

---

## 📊 MÓDULOS FUTUROS PLANEADOS

- [ ] **Mozos y atención** — Pedidos de mesas, turistas
- [ ] **Empresas turísticas** — Avalos Tours (Cusco/Puno), Inka Express (Cusco/Puno), Peru HOP, Reservas Privadas
- [ ] **Bebidas y consumos** — Control de lo que consumen los turistas
- [ ] **Reportes** — PDF y Excel de inventario y pedidos
- [ ] **Caja** — Ingresos y egresos económicos

---

## 📞 SOPORTE

Sistema desarrollado para uso interno.
Para soporte técnico, revisar primero la sección "Solución de Problemas".

---

**RESTOPRO v1.0 · 2026**  
Sistema de Gestión de Almacén para Restaurante Turístico
