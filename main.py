"""
main.py — Punto de entrada de MiniClaw

Ejecutar:  python main.py
"""
import asyncio
import logging
import sys

from dotenv import load_dotenv
load_dotenv()

from agent.agent import Agent
from matrix.client import MatrixBot
from tools.dashboard import start_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("miniclaw")


async def main():
    logger.info("🚀 Iniciando MiniClaw...")

    # Inicializar agente (crea las tablas de SQLite si no existen)
    agent = Agent()
    await agent.init()
    logger.info("✅ Agente inicializado (memoria lista)")

    # Iniciar dashboard web (background thread)
    start_dashboard()

    # Iniciar bot de Matrix
    bot = MatrixBot(agent)
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 MiniClaw detenido.")
