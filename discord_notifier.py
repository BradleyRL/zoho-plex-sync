import requests
from typing import Optional, Dict, Any
from config import config
from logger_service import logger

def send_discord_sync_summary(
    summary_data: Dict[str, Any],
    channel_id: Optional[str] = None
) -> bool:
    """
    Sends a rich Embed summary of the daily Zoho Books -> Plex sync execution
    to a designated Discord channel via Discord Webhook or Bot REST API.
    """
    webhook_url = config.DISCORD_WEBHOOK_URL.strip()
    bot_token = config.DISCORD_BOT_TOKEN.strip()
    target_channel_id = (channel_id or config.DISCORD_NOTIFICATION_CHANNEL_ID).strip()

    dry_run = summary_data.get("dry_run", False)
    threshold = summary_data.get("threshold", config.OVERDUE_DAYS_THRESHOLD)
    expired_processed = summary_data.get("expired_processed", [])
    summary = summary_data.get("summary", {})

    color = 0xF1C40F if dry_run else 0x3498DB  # Yellow for DRY-RUN, Blue for LIVE

    summary_text = (
        f"**Total a procesar:** {summary.get('total', 0)}\n"
        f"**Revocados / Actualizados:** {summary.get('success', 0)}\n"
        f"**Ya Deshabilitados:** {summary.get('already_disabled', 0)}\n"
        f"**No Encontrados en Plex:** {summary.get('not_found', 0)}\n"
        f"**Fallidos:** {summary.get('failed', 0)}"
    )

    fields = [
        {"name": "Modo", "value": "`[DRY-RUN]`" if dry_run else "`[LIVE]`", "inline": True},
        {"name": "Umbral Mora", "value": f"> {threshold} días", "inline": True},
        {"name": "Pases Expirados", "value": str(len(expired_processed)), "inline": True},
        {"name": "Resumen de Ejecución", "value": summary_text, "inline": False}
    ]

    if expired_processed:
        exp_lines = []
        for p in expired_processed[:5]:
            exp_lines.append(f"• `{p['email']}` ({p.get('customer', '')}) - Rec. Inv: `{p.get('rec_invoice', 'N/A')}`")
        fields.append({
            "name": "Pases Temporales Procesados",
            "value": "\n".join(exp_lines),
            "inline": False
        })

    embed = {
        "title": "🔄 Sincronización Diaria Zoho Books -> Plex",
        "description": "Resultado del proceso de sincronización ejecutado:",
        "color": color,
        "fields": fields
    }

    payload = {"embeds": [embed]}

    # Method 1: Send via Webhook URL if configured
    if webhook_url:
        try:
            resp = requests.post(webhook_url, json=payload, timeout=15)
            if resp.status_code in (200, 204):
                logger.info("Reporte de sincronización diario enviado exitosamente vía Webhook a Discord.")
                return True
            else:
                logger.warning(f"No se pudo enviar la notificación vía Webhook. HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Error enviando reporte vía Webhook a Discord: {e}")

    # Method 2: Send via Bot REST API
    if bot_token and target_channel_id:
        url = f"https://discord.com/api/v10/channels/{target_channel_id}/messages"
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code in (200, 201):
                logger.info(f"Reporte de sincronización diario enviado exitosamente al canal de Discord {target_channel_id}.")
                return True
            else:
                logger.warning(f"No se pudo enviar la notificación a Discord. HTTP {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Error enviando reporte de sincronización a Discord: {e}")
            return False

    logger.debug("Ni Webhook URL ni Bot Token/Channel ID válidos están configurados.")
    return False
