"""
tools/webhook_server.py — Inicializa un servidor aiohttp ligero para recibir webhooks
de n8n o servicios externos y mandarlos a Jada.
"""
import os
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

async def webhook_handler(request):
    """
    Recibe un payload POST de n8n.
    Header requerido: Authorization: Bearer <WEBHOOK_SECRET>
    Body JSON esperado:
    {
      "message": "Mensaje para enviar al chat",
      "room_id": "!xyz:matrix.org" (opcional)
    }
    """
    secret = os.getenv("WEBHOOK_SECRET")
    if not secret:
        return web.json_response({"error": "Webhook secret no configurado en Jada"}, status=500)

    # Autenticación sencilla de Bearer Token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer ") or auth_header.split(" ")[1] != secret:
        return web.json_response({"error": "No autorizado"}, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Payload JSON inválido"}, status=400)

    msg = data.get("message")
    if not msg:
        return web.json_response({"error": "Falta el campo 'message'"}, status=400)

    # Obtenemos el bot_instance del entorno web
    bot = request.app["bot_instance"]

    room_id = data.get("room_id")
    if not room_id:
        room_id = os.getenv("MATRIX_ROOM_IDS", "").split(",")[0].strip()
    if not room_id:
        # Fallback al cuarto principal de Juan si no viene en payload ni en .env
        room_id = "!DdasevfyRjYNoNhmbY:matrix.juanmontoya.me"

    logger.info(f"📨 Webhook recibido, enviando mensaje a la sala {room_id}")
    
    # Enviar mensaje al chat
    try:
        await bot.send_message(room_id, msg)
        return web.json_response({"success": True, "message": "Enviado al chat"})
    except Exception as e:
        logger.error(f"Error enviando mensaje vía webhook: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def start_webhook(bot_instance, port=8899):
    """
    Lanza el servidor aiohttp de manera no bloqueante.
    """
    if not os.getenv("WEBHOOK_SECRET"):
        logger.warning("⚠️ No se definió WEBHOOK_SECRET en .env, el webhook no iniciará.")
        return

    app = web.Application()
    app["bot_instance"] = bot_instance
    app.router.add_post("/webhook", webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"🌐 Webhook listener iniciado en puerto {port}")
