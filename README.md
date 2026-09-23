# Zoho Books to Plex Overdue Invoice Sync & Access Manager

Script en Python que sincroniza las facturas vencidas de **Zoho Books** (con mora mayor a 3 días) con el control de acceso a librerías de usuarios en **Plex Media Server**.

Permite además gestionar pases temporales por 2 días, pases permanentes, restituir accesos por número de factura recurrente y listar usuarios compartidos en Plex que no posean una suscripción activa.

---

## Características Principales

1. **Control de Mora Automático**:
   - Detecta clientes con facturas en mora mayores a 3 días en Zoho Books.
   - Modifica o revoca las librerías configuradas en Plex.
   - Genera logs diarios en `logs/disabled_users_YYYY-MM-DD.log`.

2. **4 Opciones de Gestión de Accesos por CLI**:
   - **`--grant-temp EMAIL [--days 2]`**: Otorga acceso temporal por 2 días. Al vencer los 2 días, el script revoca el acceso automáticamente.
   - **`--grant-invoice RECURRING_INVOICE_NUM`**: Busca el número de factura recurrente en Zoho Books y le restituye el acceso al usuario.
   - **`--grant-permanent EMAIL`**: Otorga acceso permanente y omite la suspensión por mora.
   - **`--list-inactive-plex`**: Muestra una lista de los usuarios de Plex que **NO** tienen una factura recurrente activa en Zoho Books.

---

## Requisitos y Configuración

### 1. Instalar Dependencias
```bash
python3 -m pip install -r requirements.txt
```

### 2. Configurar Variables de Entorno
Copia `.env.example` a `.env` y configura tus credenciales:
```bash
cp .env.example .env
```

Contenido de `.env`:
```env
# Zoho Books OAuth 2.0
ZOHO_CLIENT_ID=1000.XXXXXXXXXXXXXXXXXXXXXXXX
ZOHO_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ZOHO_REFRESH_TOKEN=1000.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ZOHO_ORGANIZATION_ID=123456789
ZOHO_DOMAIN=com

# Plex Configuration
PLEX_TOKEN=tu_plex_token
PLEX_SERVER_NAME= # Opcional si tienes más de un servidor

# Librerías a revocar (separadas por coma)
# Si se deja vacío o "ALL", se elimina el acceso completo al servidor
PLEX_LIBRARIES=Peliculas,Series

# Días de mora requeridos
OVERDUE_DAYS_THRESHOLD=3
```

---

## Uso del Script

### Comandos de Gestión

```bash
# Validar configuración
python3 main.py --check-config

# 1. Acceso temporal por 2 días
python3 main.py --grant-temp usuario@ejemplo.com --days 2

# 2. Restablecer acceso enviando el # de factura recurrente de Zoho
python3 main.py --grant-invoice REC-INV-1002

# 3. Acceso permanente
python3 main.py --grant-permanent cliente_vip@ejemplo.com

# 4. Listar usuarios de Plex sin factura recurrente activa en Zoho
python3 main.py --list-inactive-plex

# Probar ejecuciones sin alterar Plex (Simulación)
python3 main.py --dry-run
```

### Sincronización Diaria Automática (Cron)
Para ejecutar el script diariamente a las 02:00 AM:

```cron
0 2 * * * cd /ruta/al/proyecto && /usr/bin/python3 main.py >> logs/cron.log 2>&1
```

---

## Pruebas Automatizadas

Para ejecutar las pruebas unitarias:
```bash
python3 -m pytest tests/
```
