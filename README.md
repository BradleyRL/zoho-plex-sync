# Zoho Books to Plex Overdue Invoice Sync & Access Manager

Script en Python que sincroniza las facturas vencidas de **Zoho Books** (con mora mayor a 3 días) con el control de acceso a librerías de usuarios en **Plex Media Server**.

Permite además gestionar pases temporales por 2 días (o 3 días si se otorga un Viernes para cubrir el fin de semana completo), pases permanentes, restituir accesos por número de factura recurrente y listar usuarios compartidos en Plex que no posean una suscripción activa.

---

## Características Principales

1. **Control de Mora Automático**:
   - Detecta clientes con facturas en mora mayores a 3 días en Zoho Books.
   - Modifica o revoca las librerías configuradas en Plex para **todos** los usuarios en mora (incluyendo aquellos con pase permanente).
   - Para facturas con 20+ días de mora, anula automáticamente la factura (estado `VOID` con la razón "No Renovó") y detiene (`STOP`) las facturas recurrentes activas del cliente en Zoho Books.
   - Genera logs diarios en `logs/disabled_users_YYYY-MM-DD.log`.

2. **5 Opciones de Gestión de Accesos por CLI**:
   - **`--grant-temp EMAIL --name "NOMBRE CLIENTE" [--days 2]`**: Crea/asocia el cliente en Zoho Books (`currency_code="GTQ"`), guarda su `customer_id` y le otorga acceso temporal por 2 días (o 3 días si es Viernes). Al vencer el pase, el script revoca el acceso en Plex y crea automáticamente una Factura Recurrente en Zoho Books.
   - **`--grant-invoice RECURRING_INVOICE_NUM`**: Busca el número de factura recurrente en Zoho Books y le restituye el acceso al usuario.
   - **`--grant-permanent EMAIL`**: Otorga acceso permanente en Plex (sin temporizador de expiración). **Sujeto a desactivación si presenta facturas en mora mayores a 3 días en Zoho Books**.
   - **`--list-inactive-plex`**: Muestra una lista de los usuarios de Plex que **NO** tienen una factura recurrente activa en Zoho Books.
   - **`--revoke-access EMAIL`**: Revoca inmediatamente el acceso a librerías en Plex para el correo especificado.

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

# Configuración del Bot de Discord
DISCORD_BOT_TOKEN=tu_token_de_bot_discord
DISCORD_ALLOWED_USERS=123456789012345678,987654321098765432
DISCORD_GUILD_ID=123456789012345678
DISCORD_NOTIFICATION_CHANNEL_ID=1552699204772696267 # Canal para recibir reporte diario de sincronización
```

---

## Uso del Script

### Comandos de Gestión

```bash
# Validar configuración
python3 main.py --check-config

# 1. Acceso temporal (requiere --name, crea cliente en Zoho GTQ y Factura Recurrente al vencer)
python3 main.py --grant-temp usuario@ejemplo.com --name "Nombre Cliente"

# 2. Restablecer acceso enviando el # de factura recurrente de Zoho
python3 main.py --grant-invoice REC-INV-1002

# 3. Acceso permanente (sujeto a control diario de mora en Zoho Books)
python3 main.py --grant-permanent cliente_vip@ejemplo.com

# 4. Listar usuarios de Plex sin factura recurrente activa en Zoho
python3 main.py --list-inactive-plex

# 5. Revocar acceso a Plex por correo directamente
python3 main.py --revoke-access usuario@ejemplo.com

# Probar ejecuciones sin alterar Plex (Simulación)
python3 main.py --dry-run
```

---

## Bot de Discord (Slash Commands)

Puedes ejecutar el bot de Discord para administrar todos los comandos desde tu servidor usando **Slash Commands**:

```bash
python3 discord_bot.py
```

### Comandos Disponibles en Discord:
- **`/grant_temp <email> <name> [days] [dry_run]`**: Otorga un pase temporal, registra al cliente en Zoho Books (`GTQ`) y crea Factura Recurrente al vencer.
- **`/grant_invoice <invoice_num> [dry_run]`**: Restablece acceso buscando por el número de factura recurrente.
- **`/grant_permanent <email> [dry_run]`**: Otorga un pase permanente en Plex.
- **`/revoke_access <email> [dry_run]`**: Revoca el acceso de librerías en Plex para un correo directamente.
- **`/list_inactive_plex`**: Muestra usuarios de Plex sin factura recurrente activa en Zoho.
- **`/show_invoices [threshold]`**: Consulta facturas pendientes/vencidas en Zoho Books.
- **`/sync [dry_run] [threshold]`**: Ejecuta el proceso de sincronización diaria completo (vencimientos, pases expirados, anulación por 20+ días de mora).
- **`/check_config`**: Valida las credenciales y configuración del sistema.
- **`/help`**: Despliega el menú de ayuda interactivo con Embeds.

---

## Sincronización Diaria Automática (Cron)
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
