"""
main.py — Punto de entrada de Jada

Ejecutar:  python main.py
"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from agent.agent import Agent
from matrix.client import MatrixBot
from tools.dashboard import start_dashboard

VERSION = "0.5.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("jada")


def print_banner():
    """Imprime el banner ASCII de Jada al iniciar el servidor."""
    # Colores ANSI
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    banner = f"""
{CYAN}{BOLD}
     ██╗ █████╗ ██████╗  █████╗
     ██║██╔══██╗██╔══██╗██╔══██╗
     ██║███████║██║  ██║███████║
██   ██║██╔══██║██║  ██║██╔══██║
╚█████╔╝██║  ██║██████╔╝██║  ██║
 ╚════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝{RESET}

{MAGENTA}  ╔══════════════════════════════════════════╗
  ║{RESET}  {BOLD}Personal AI Agent{RESET}  {DIM}— powered by NVIDIA NIM{RESET}  {MAGENTA}║
  ╚══════════════════════════════════════════╝{RESET}

  {DIM}Version:{RESET}  {YELLOW}{VERSION}{RESET}
  {DIM}Model:{RESET}    {GREEN}{os.getenv("NVIDIA_MODEL", "N/A")}{RESET}
  {DIM}Matrix:{RESET}   {GREEN}{os.getenv("MATRIX_HOMESERVER", "N/A")}{RESET}
  {DIM}Dashboard:{RESET} {GREEN}http://localhost:8080{RESET}
"""
    print(banner)


async def main():
    print_banner()
    logger.info("🚀 Iniciando Jada...")

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
        logger.info("👋 Jada detenida.")
