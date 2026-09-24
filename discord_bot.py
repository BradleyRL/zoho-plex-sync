#!/usr/bin/env python3
"""
Discord Bot for Zoho Books <-> Plex Sync Management.

Allows authorized Discord users to execute all CLI commands via slash commands:
 - /grant_temp <email> <name> [days] [dry_run]
 - /grant_invoice <invoice_num> [dry_run]
 - /grant_permanent <email> [dry_run]
 - /list_inactive_plex
 - /show_invoices [threshold]
 - /sync [dry_run] [threshold]
 - /check_config
 - /help
"""

import sys
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from config import config
from logger_service import logger, log_disabled_user
from zoho_service import ZohoBooksService
from plex_service import PlexService
from grant_service import GrantService

# Setup Discord Client & Command Tree
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

def is_authorized(user_id: int) -> bool:
    """Checks whether the Discord user ID is allowed to run commands."""
    allowed = config.DISCORD_ALLOWED_USERS
    if not allowed:
        # If DISCORD_ALLOWED_USERS is empty, allow all users by default
        return True
    return user_id in allowed

def check_auth_or_embed(interaction: discord.Interaction) -> discord.Embed | None:
    """Returns an unauthorized embed if the user is not in DISCORD_ALLOWED_USERS."""
    if not is_authorized(interaction.user.id):
        embed = discord.Embed(
            title="🚫 Acceso No Autorizado",
            description=f"Tu ID de usuario (`{interaction.user.id}`) no tiene permiso para ejecutar este comando.",
            color=discord.Color.red()
        )
        return embed
    return None

def check_system_config() -> list[str]:
    """Validates core environment configuration."""
    return config.validate()

# ==============================================================================
# SLASH COMMANDS
# ==============================================================================

@bot.tree.command(name="grant_temp", description="Opción 1: Otorgar acceso temporal (N días) y crear cliente en Zoho Books")
@app_commands.describe(
    email="Correo electrónico del usuario de Plex",
    name="Nombre del cliente para Zoho Books",
    days="Días de acceso temporal (por defecto: 2)",
    dry_run="Simular sin modificar Plex ni Zoho Books"
)
async def grant_temp(
    interaction: discord.Interaction,
    email: str,
    name: str,
    days: int = 2,
    dry_run: bool = False
):
    unauth_embed = check_auth_or_embed(interaction)
    if unauth_embed:
        await interaction.response.send_message(embed=unauth_embed, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    def _execute():
        missing = check_system_config()
        if missing:
            return {"error": f"Configuración incompleta: {', '.join(missing)}"}

        zoho_service = ZohoBooksService(cfg=config)
        plex_service = PlexService(cfg=config)
        grant_service = GrantService()

        # Step 1: Create customer in Zoho Books
        if dry_run:
            customer_id = "DRY_RUN_CUSTOMER_ID"
        else:
            try:
                customer_id = zoho_service.create_customer(contact_name=name, email=email, currency_code="GTQ")
            except Exception as e:
                return {"error": f"Error al crear cliente en Zoho Books: {e}"}

        # Step 2: Register temporary pass
        pass_info = grant_service.add_temporary_pass(
            email=email,
            customer_name=name,
            customer_id=customer_id,
            days=days
        )

        # Step 3: Grant access in Plex
        result = plex_service.grant_user_access(email=email, dry_run=dry_run)

        log_disabled_user(
            email=email,
            customer_name=name,
            invoice_numbers=["TEMP-PASS"],
            max_days_overdue=0,
            action=f"Granted temporary access ({days} days, expires {pass_info['expires_at']})",
            status=result["status"],
            dry_run=dry_run
        )

        return {
            "email": email,
            "name": name,
            "days": days,
            "expires_at": pass_info["expires_at"],
            "customer_id": customer_id,
            "status": result["status"],
            "message": result.get("message", ""),
            "dry_run": dry_run
        }

    data = await asyncio.to_thread(_execute)

    if "error" in data:
        embed = discord.Embed(
            title="❌ Error al Otorgar Acceso Temporal",
            description=data["error"],
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return

    color = discord.Color.gold() if dry_run else discord.Color.green()
    embed = discord.Embed(
        title="🎟️ Acceso Temporal Otorgado",
        color=color
    )
    embed.add_field(name="Cliente", value=data["name"], inline=True)
    embed.add_field(name="Email", value=data["email"], inline=True)
    embed.add_field(name="Días de Acceso", value=str(data["days"]), inline=True)
    embed.add_field(name="Vencimiento", value=data["expires_at"], inline=False)
    embed.add_field(name="Zoho Customer ID", value=data["customer_id"], inline=True)
    embed.add_field(name="Estado Plex", value=f"`{data['status']}`", inline=True)
    embed.add_field(name="Modo", value="`[DRY-RUN]`" if dry_run else "`[LIVE]`", inline=True)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="grant_invoice", description="Opción 2: Otorgar acceso por # de factura recurrente en Zoho Books")
@app_commands.describe(
    invoice_num="Número de Factura Recurrente (o factura)",
    dry_run="Simular sin modificar Plex"
)
async def grant_invoice(
    interaction: discord.Interaction,
    invoice_num: str,
    dry_run: bool = False
):
    unauth_embed = check_auth_or_embed(interaction)
    if unauth_embed:
        await interaction.response.send_message(embed=unauth_embed, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    def _execute():
        missing = check_system_config()
        if missing:
            return {"error": f"Configuración incompleta: {', '.join(missing)}"}

        zoho_service = ZohoBooksService(cfg=config)
        plex_service = PlexService(cfg=config)
        grant_service = GrantService()

        info = zoho_service.get_email_by_recurring_invoice(invoice_num)
        if not info or not info.get("email"):
            return {"error": f"No se encontró correo de cliente para la factura recurrente `{invoice_num}`."}

        email = info["email"]
        customer_name = info.get("customer_name", "Customer")
        rec_num = info.get("recurring_invoice_number", invoice_num)

        grant_service.remove_pass(email)
        result = plex_service.grant_user_access(email=email, dry_run=dry_run)

        log_disabled_user(
            email=email,
            customer_name=customer_name,
            invoice_numbers=[f"REC-INV:{rec_num}"],
            max_days_overdue=0,
            action=f"Granted access via recurring invoice #{rec_num}",
            status=result["status"],
            dry_run=dry_run
        )

        return {
            "email": email,
            "customer_name": customer_name,
            "recurring_invoice": rec_num,
            "status": result["status"],
            "dry_run": dry_run
        }

    data = await asyncio.to_thread(_execute)

    if "error" in data:
        embed = discord.Embed(
            title="❌ Error al Otorgar Acceso por Factura",
            description=data["error"],
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return

    color = discord.Color.gold() if dry_run else discord.Color.green()
    embed = discord.Embed(
        title="📄 Acceso Otorgado por Factura Recurrente",
        color=color
    )
    embed.add_field(name="Factura Recurrente #", value=data["recurring_invoice"], inline=True)
    embed.add_field(name="Cliente", value=data["customer_name"], inline=True)
    embed.add_field(name="Email", value=data["email"], inline=False)
    embed.add_field(name="Estado Plex", value=f"`{data['status']}`", inline=True)
    embed.add_field(name="Modo", value="`[DRY-RUN]`" if dry_run else "`[LIVE]`", inline=True)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="grant_permanent", description="Opción 3: Otorgar acceso permanente a un correo electrónico")
@app_commands.describe(
    email="Correo electrónico del usuario de Plex",
    dry_run="Simular sin modificar Plex"
)
async def grant_permanent(
    interaction: discord.Interaction,
    email: str,
    dry_run: bool = False
):
    unauth_embed = check_auth_or_embed(interaction)
    if unauth_embed:
        await interaction.response.send_message(embed=unauth_embed, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    def _execute():
        missing = check_system_config()
        if missing:
            return {"error": f"Configuración incompleta: {', '.join(missing)}"}

        plex_service = PlexService(cfg=config)
        grant_service = GrantService()

        grant_service.add_permanent_pass(email=email)
        result = plex_service.grant_user_access(email=email, dry_run=dry_run)

        log_disabled_user(
            email=email,
            customer_name="Permanent Pass",
            invoice_numbers=["PERMANENT-PASS"],
            max_days_overdue=0,
            action="Granted permanent library access",
            status=result["status"],
            dry_run=dry_run
        )

        return {
            "email": email,
            "status": result["status"],
            "dry_run": dry_run
        }

    data = await asyncio.to_thread(_execute)

    if "error" in data:
        embed = discord.Embed(
            title="❌ Error al Otorgar Acceso Permanente",
            description=data["error"],
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return

    color = discord.Color.gold() if dry_run else discord.Color.green()
    embed = discord.Embed(
        title="♾️ Acceso Permanente Otorgado",
        color=color
    )
    embed.add_field(name="Email", value=data["email"], inline=True)
    embed.add_field(name="Estado Plex", value=f"`{data['status']}`", inline=True)
    embed.add_field(name="Modo", value="`[DRY-RUN]`" if dry_run else "`[LIVE]`", inline=True)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="list_inactive_plex", description="Opción 4: Listar usuarios de Plex sin factura recurrente ACTIVA en Zoho")
async def list_inactive_plex(interaction: discord.Interaction):
    unauth_embed = check_auth_or_embed(interaction)
    if unauth_embed:
        await interaction.response.send_message(embed=unauth_embed, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    def _execute():
        missing = check_system_config()
        if missing:
            return {"error": f"Configuración incompleta: {', '.join(missing)}"}

        zoho_service = ZohoBooksService(cfg=config)
        plex_service = PlexService(cfg=config)
        grant_service = GrantService()

        try:
            plex_users = plex_service.get_all_shared_users()
        except Exception as e:
            return {"error": f"Error al obtener usuarios de Plex: {e}"}

        if not plex_users:
            return {"users": [], "message": "No se encontraron usuarios compartidos en Plex."}

        try:
            active_emails = zoho_service.get_active_recurring_invoice_emails()
        except Exception as e:
            return {"error": f"Error al obtener facturas de Zoho: {e}"}

        inactive_plex_users = []
        for u in plex_users:
            email = u.get("email")
            username = u.get("username")
            title = u.get("title")

            is_active_in_zoho = (
                (email and email in active_emails) or
                (username and username.lower() in active_emails) or
                (title and title.lower() in active_emails)
            )

            has_perm_pass = grant_service.is_permanently_allowed(email) if email else False
            has_temp_pass = grant_service.is_temporary_active(email) if email else False

            if not is_active_in_zoho:
                reason = "Sin factura recurrente activa"
                if has_perm_pass:
                    reason += " (Pase PERMANENTE)"
                elif has_temp_pass:
                    reason += " (Pase TEMPORAL activo)"

                inactive_plex_users.append({
                    "email": email or "(Sin Email)",
                    "username": username or title or "Desconocido",
                    "reason": reason
                })

        return {"users": inactive_plex_users}

    data = await asyncio.to_thread(_execute)

    if "error" in data:
        embed = discord.Embed(
            title="❌ Error al Listar Usuarios Inactivos",
            description=data["error"],
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return

    users = data.get("users", [])
    embed = discord.Embed(
        title="⚠️ Usuarios Plex Sin Factura Recurrente Activa",
        description=f"Total de usuarios inactivos detectados: **{len(users)}**",
        color=discord.Color.orange()
    )

    if not users:
        embed.description = "✅ ¡Todos los usuarios de Plex tienen una factura recurrente activa en Zoho Books!"
        await interaction.followup.send(embed=embed)
        return

    # Add fields up to 25 fields max (Discord embed limit)
    for index, u in enumerate(users[:25]):
        embed.add_field(
            name=f"{index + 1}. {u['username']}",
            value=f"**Email:** {u['email']}\n**Nota:** {u['reason']}",
            inline=False
        )

    if len(users) > 25:
        embed.set_footer(text=f"Mostrando los primeros 25 de {len(users)} usuarios.")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="show_invoices", description="Debug: Mostrar facturas pendientes/vencidas en Zoho Books")
@app_commands.describe(threshold="Días de mora para considerar vencida (por defecto desde env)")
async def show_invoices(interaction: discord.Interaction, threshold: int | None = None):
    unauth_embed = check_auth_or_embed(interaction)
    if unauth_embed:
        await interaction.response.send_message(embed=unauth_embed, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    eff_threshold = threshold if threshold is not None else config.OVERDUE_DAYS_THRESHOLD

    def _execute():
        missing = check_system_config()
        if missing:
            return {"error": f"Configuración incompleta: {', '.join(missing)}"}

        zoho_service = ZohoBooksService(cfg=config)

        try:
            invoices = zoho_service.get_overdue_invoices()
        except Exception as e:
            return {"error": f"Error al consultar facturas en Zoho Books: {e}"}

        items = []
        for inv in invoices:
            num = inv.get("invoice_number", "UNKNOWN")
            name = inv.get("customer_name", "Desconocido")
            email = inv.get("email") or inv.get("customer_email") or "(Sin Email)"
            due_date = inv.get("due_date", "N/A")
            
            days_overdue = 0
            if due_date != "N/A":
                try:
                    days_overdue = zoho_service.calculate_days_overdue(due_date)
                except Exception:
                    pass

            is_overdue = days_overdue > eff_threshold
            items.append({
                "number": num,
                "customer": name,
                "email": email,
                "due_date": due_date,
                "days_overdue": days_overdue,
                "is_overdue": is_overdue
            })

        return {"invoices": items}

    data = await asyncio.to_thread(_execute)

    if "error" in data:
        embed = discord.Embed(
            title="❌ Error al Consultar Facturas",
            description=data["error"],
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return

    invoices = data.get("invoices", [])
    embed = discord.Embed(
        title="📊 Facturas Pendientes / Vencidas en Zoho Books",
        description=f"Total encontradas: **{len(invoices)}** (Umbral: > {eff_threshold} días)",
        color=discord.Color.blue()
    )

    if not invoices:
        embed.description = "✅ No se encontraron facturas pendientes o vencidas en Zoho Books."
        await interaction.followup.send(embed=embed)
        return

    for index, inv in enumerate(invoices[:20]):
        status_tag = "🔴 **REVOCABLE**" if inv["is_overdue"] else "🟢 Al día / Gracia"
        embed.add_field(
            name=f"Factura #{inv['number']} - {inv['customer']}",
            value=f"**Email:** {inv['email']}\n**Vencimiento:** {inv['due_date']} ({inv['days_overdue']} días)\n**Estado:** {status_tag}",
            inline=False
        )

    if len(invoices) > 20:
        embed.set_footer(text=f"Mostrando 20 de {len(invoices)} facturas.")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="sync", description="Ejecutar sincronización diaria Zoho Books -> Plex")
@app_commands.describe(
    dry_run="Simular sincronización sin revocar accesos ni crear facturas",
    threshold="Anular umbral de días vencidos (por defecto desde env)"
)
async def sync(
    interaction: discord.Interaction,
    dry_run: bool = False,
    threshold: int | None = None
):
    unauth_embed = check_auth_or_embed(interaction)
    if unauth_embed:
        await interaction.response.send_message(embed=unauth_embed, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    eff_threshold = threshold if threshold is not None else config.OVERDUE_DAYS_THRESHOLD

    def _execute():
        missing = check_system_config()
        if missing:
            return {"error": f"Configuración incompleta: {', '.join(missing)}"}

        zoho_service = ZohoBooksService(cfg=config)
        plex_service = PlexService(cfg=config)
        grant_service = GrantService()

        # STEP 1: Process expired temporary passes
        expired_passes = grant_service.get_expired_temporary_passes()
        expired_processed = []
        today_str = datetime.now().strftime("%Y-%m-%d")

        if expired_passes:
            for pass_info in expired_passes:
                expired_email = pass_info["email"]
                customer_name = pass_info.get("customer_name") or expired_email
                customer_id = pass_info.get("customer_id")

                rec_inv_status = "N/A"
                if customer_id:
                    if dry_run:
                        rec_inv_status = "[DRY-RUN] Se crearía factura recurrente"
                    else:
                        try:
                            zoho_service.create_recurring_invoice(
                                customer_id=customer_id,
                                recurrence_name=customer_name,
                                start_date=today_str,
                                item_id="5251269000000090022",
                                quantity=1,
                                never_expires=True,
                                payment_terms=0
                            )
                            rec_inv_status = "Creada exitosamente"
                        except Exception as e:
                            rec_inv_status = f"Error: {e}"

                revoke_res = plex_service.revoke_user_access(email=expired_email, dry_run=dry_run)
                log_disabled_user(
                    email=expired_email,
                    customer_name=f"{customer_name} (Expired Pass)",
                    invoice_numbers=["EXPIRED-PASS"],
                    max_days_overdue=0,
                    action="Access revoked & recurring invoice created: temporary pass expired",
                    status=revoke_res["status"],
                    dry_run=dry_run
                )
                expired_processed.append({
                    "email": expired_email,
                    "customer": customer_name,
                    "status": revoke_res["status"],
                    "rec_invoice": rec_inv_status
                })

        # STEP 2: Process Zoho Books Overdue Invoices
        try:
            users_to_disable = zoho_service.get_users_to_disable(days_threshold=eff_threshold)
        except Exception as e:
            return {"error": f"Error al consultar facturas vencidas en Zoho: {e}"}

        filtered_users = []
        for u in users_to_disable:
            if grant_service.is_temporary_active(u["email"]):
                continue
            filtered_users.append(u)

        summary = {
            "total": len(filtered_users),
            "success": 0,
            "already_disabled": 0,
            "not_found": 0,
            "failed": 0
        }

        revoked_list = []

        for user_info in filtered_users:
            email = user_info["email"]
            customer_name = user_info["customer_name"]
            invoice_numbers = user_info["invoice_numbers"]
            max_days = user_info["max_days_overdue"]

            res = plex_service.revoke_user_access(email=email, dry_run=dry_run)

            log_disabled_user(
                email=email,
                customer_name=customer_name,
                invoice_numbers=invoice_numbers,
                max_days_overdue=max_days,
                action=res["action"],
                status=res["status"],
                dry_run=dry_run
            )

            st = res["status"]
            if st in ("SUCCESS", "DRY_RUN"):
                summary["success"] += 1
            elif st == "ALREADY_DISABLED":
                summary["already_disabled"] += 1
            elif st == "NOT_FOUND":
                summary["not_found"] += 1
            else:
                summary["failed"] += 1

            revoked_list.append({
                "email": email,
                "customer": customer_name,
                "invoices": ", ".join(invoice_numbers),
                "status": st
            })

        return {
            "dry_run": dry_run,
            "threshold": eff_threshold,
            "expired_processed": expired_processed,
            "summary": summary,
            "revoked_list": revoked_list
        }

    data = await asyncio.to_thread(_execute)

    if "error" in data:
        embed = discord.Embed(
            title="❌ Error Durante la Sincronización",
            description=data["error"],
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return

    color = discord.Color.gold() if dry_run else discord.Color.blue()
    embed = discord.Embed(
        title="🔄 Sincronización Zoho Books -> Plex Finalizada",
        color=color
    )
    embed.add_field(name="Modo", value="`[DRY-RUN]`" if dry_run else "`[LIVE]`", inline=True)
    embed.add_field(name="Umbral de Vencimiento", value=f"> {data['threshold']} días", inline=True)
    embed.add_field(name="Pases Temporales Expirados", value=str(len(data["expired_processed"])), inline=True)

    summary = data["summary"]
    summary_text = (
        f"**Total a procesar:** {summary['total']}\n"
        f"**Revocados / Actualizados:** {summary['success']}\n"
        f"**Ya Deshabilitados:** {summary['already_disabled']}\n"
        f"**No Encontrados en Plex:** {summary['not_found']}\n"
        f"**Fallidos:** {summary['failed']}"
    )
    embed.add_field(name="Resumen de Ejecución", value=summary_text, inline=False)

    if data["expired_processed"]:
        exp_text = "\n".join([f"• `{p['email']}` - Status: `{p['status']}`" for p in data["expired_processed"][:5]])
        embed.add_field(name="Pases Temporales Procesados", value=exp_text, inline=False)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="check_config", description="Validar la configuración y variables de entorno del sistema")
async def check_config(interaction: discord.Interaction):
    unauth_embed = check_auth_or_embed(interaction)
    if unauth_embed:
        await interaction.response.send_message(embed=unauth_embed, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    missing = check_system_config()

    if missing:
        embed = discord.Embed(
            title="⚙️ Estado de la Configuración: INCOMPLETA",
            description=f"Faltan las siguientes variables en `.env`:\n• " + "\n• ".join(missing),
            color=discord.Color.red()
        )
    else:
        embed = discord.Embed(
            title="⚙️ Estado de la Configuración: VÁLIDA",
            description="Todas las variables requeridas están correctamente configuradas.",
            color=discord.Color.green()
        )
        embed.add_field(name="Plex Server", value=f"`{config.PLEX_SERVER_NAME}`" or "No set", inline=True)
        embed.add_field(name="Zoho Domain", value=f"`{config.ZOHO_DOMAIN}`", inline=True)
        embed.add_field(name="Umbral Mora", value=f"`{config.OVERDUE_DAYS_THRESHOLD}` días", inline=True)
        embed.add_field(name="Usuarios Autorizados Discord", value=f"`{len(config.DISCORD_ALLOWED_USERS)}` registrados", inline=False)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="help", description="Mostrar menú de ayuda con todos los comandos disponibles")
async def help_command(interaction: discord.Interaction):
    unauth_embed = check_auth_or_embed(interaction)
    if unauth_embed:
        await interaction.response.send_message(embed=unauth_embed, ephemeral=True)
        return

    embed = discord.Embed(
        title="🤖 Bot de Gestión Zoho Books <-> Plex",
        description="Comandos disponibles para administrar accesos de Plex y sincronización con Zoho Books:",
        color=discord.Color.purple()
    )
    embed.add_field(
        name="🎟️ `/grant_temp <email> <name> [days] [dry_run]`",
        value="Otorga acceso temporal N días, crea cliente en Zoho (GTQ) y guarda ID para facturación recurrente futura.",
        inline=False
    )
    embed.add_field(
        name="📄 `/grant_invoice <invoice_num> [dry_run]`",
        value="Otorga acceso a usuario buscando por número de factura recurrente de Zoho.",
        inline=False
    )
    embed.add_field(
        name="♾️ `/grant_permanent <email> [dry_run]`",
        value="Otorga acceso permanente en Plex evitando revocaciones automáticas.",
        inline=False
    )
    embed.add_field(
        name="⚠️ `/list_inactive_plex`",
        value="Muestra usuarios de Plex que NO poseen una factura recurrente activa en Zoho Books.",
        inline=False
    )
    embed.add_field(
        name="📊 `/show_invoices [threshold]`",
        value="Muestra todas las facturas pendientes/vencidas en Zoho Books.",
        inline=False
    )
    embed.add_field(
        name="🔄 `/sync [dry_run] [threshold]`",
        value="Ejecuta la sincronización diaria completa (vencimientos, pases expirados y facturas recurrentes).",
        inline=False
    )
    embed.add_field(
        name="⚙️ `/check_config`",
        value="Verifica que las credenciales y variables del entorno (.env) estén correctas.",
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=False)


# ==============================================================================
# BOT EVENT HANDLERS
# ==============================================================================

@bot.event
async def on_ready():
    logger.info(f"Bot conectado exitosamente como {bot.user} (ID: {bot.user.id})")
    
    guild_id = config.DISCORD_GUILD_ID
    if guild_id and guild_id.isdigit():
        guild_obj = discord.Object(id=int(guild_id))
        bot.tree.copy_global_to(guild=guild_obj)
        synced = await bot.tree.sync(guild=guild_obj)
        logger.info(f"Sincronizados {len(synced)} comando(s) de barra diagonal en el servidor Guild ID: {guild_id}")
    else:
        synced = await bot.tree.sync()
        logger.info(f"Sincronizados {len(synced)} comando(s) de barra diagonal globalmente.")

def main():
    token = config.DISCORD_BOT_TOKEN
    if not token:
        logger.error("Error: DISCORD_BOT_TOKEN no está configurado en el archivo .env.")
        sys.exit(1)

    logger.info("Iniciando Bot de Discord...")
    bot.run(token)

if __name__ == "__main__":
    main()
