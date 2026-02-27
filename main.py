"""
main.py — Punto de entrada de Jada

Uso:
  python main.py            → modo silencioso (solo banner, sin logs de consola)
  python main.py --livelogs → modo verbose (logs completos en consola)
"""
import asyncio
import argparse
import logging
import os
import sys
import atexit

from dotenv import load_dotenv
load_dotenv()

from agent.agent import Agent
from matrix.client import MatrixBot
from tools.dashboard import start_dashboard

VERSION = "0.5.2"
PIDFILE = os.getenv("JADA_PIDFILE", "jada.pid")


def _acquire_lock() -> bool:
    """Crea un PID lock para evitar dos instancias simultáneas. Retorna True si OK."""
    if os.path.exists(PIDFILE):
        try:
            with open(PIDFILE) as f:
                old_pid = int(f.read().strip())
            # Verificar si el proceso anterior sigue vivo
            import psutil
            if psutil.pid_exists(old_pid):
                return False  # otra instancia activa
        except Exception:
            pass  # PID file corrupto o psutil no instalado — continuar
    # Escribir PID actual
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(PIDFILE) and os.unlink(PIDFILE))
    return True


def setup_logging(live_logs: bool) -> None:
    """Configura el nivel de logging según el modo de ejecución."""
    if live_logs:
        # Modo verbose: todo en consola con formato completo
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
        )
    else:
        # Modo silencioso: solo WARNING+ en consola, todo a archivo de log
        log_file = os.getenv("LOG_FILE", "jada.log")

        # Handler de archivo (captura todo)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

        # Handler de consola (solo errores críticos)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(logging.Formatter("%(message)s"))

        logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console_handler])


def print_banner(live_logs: bool = False) -> None:
    """Imprime el banner ASCII de Jada al iniciar el servidor."""
    CYAN    = "\033[96m"
    MAGENTA = "\033[95m"
    YELLOW  = "\033[93m"
    GREEN   = "\033[92m"
    DIM     = "\033[2m"
    BOLD    = "\033[1m"
    RESET   = "\033[0m"

    mode_label = f"{YELLOW}--livelogs{RESET}" if live_logs else f"{DIM}silencioso  (usa --livelogs para ver logs){RESET}"

    banner = f"""
{CYAN}{BOLD}
     ██╗ █████╗ ██████╗  █████╗
     ██║██╔══██╗██╔══██╗██╔══██╗
     ██║███████║██║  ██║███████║
██   ██║██╔══██║██║  ██║██╔══██║
╚█████╔╝██║  ██║██████╔╝██║  ██║
 ╚════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝{RESET}

{MAGENTA}  ╔══════════════════════════════════════════╗
  ║{RESET}       {BOLD}Personal AI Agent{RESET}  {DIM}— 5panes{RESET}           {MAGENTA}║
  ╚══════════════════════════════════════════╝{RESET}

  {DIM}Version:{RESET}  {YELLOW}{VERSION}{RESET}
  {DIM}Model:{RESET}    {GREEN}{os.getenv("NVIDIA_MODEL", "N/A")}{RESET}
  {DIM}Matrix:{RESET}   {GREEN}{os.getenv("MATRIX_HOMESERVER", "N/A")}{RESET}
  {DIM}Dashboard:{RESET} {GREEN}http://localhost:3000{RESET}
  {DIM}Modo:{RESET}     {mode_label}
"""
    print(banner)


async def main(live_logs: bool = False) -> None:
    logger = logging.getLogger("jada")
    logger.info("🚀 Iniciando Jada...")

    # Inicializar agente
    agent = Agent()
    await agent.init()
    logger.info("✅ Agente inicializado (memoria lista)")

    # Iniciar dashboard web
    start_dashboard()

    # Iniciar bot de Matrix
    bot = MatrixBot(agent)

    # Inicializar y arrancar scheduler
    from agent.scheduler import init_scheduler
    from agent.heartbeat import run_heartbeat, _parse_heartbeat_config
    scheduler = init_scheduler(agent.run_scheduled)
    agent.set_send_callback(bot.send_message)
    scheduler.set_agent(agent)   # ← heartbeat necesita llm + send_callback
    await scheduler.start()
    logger.info("✅ Scheduler de tareas programadas iniciado")

    # Registrar heartbeat como tarea programada
    hb_config = _parse_heartbeat_config()
    if hb_config["enabled"]:
        hb_room = hb_config["room_id"] or (list(scheduler.list_jobs())[0].get("room_id", "") if scheduler.list_jobs() else "")
        existing_hb = [j for j in scheduler.list_jobs() if j.get("name") == "__heartbeat__"]
        if not existing_hb:
            scheduler.add_job(
                job_id="__heartbeat__",
                name="__heartbeat__",
                cron_expr=hb_config["cron_expr"],
                prompt="__heartbeat__",  # señal especial
                room_id=hb_room,
            )
        logger.info(f"💓 Heartbeat registrado (cron={hb_config['cron_expr']}, prob={hb_config['speak_probability']}%)")

    await bot.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Jada — Personal AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modos:
  python main.py            → Modo silencioso (solo el banner, logs en jada.log)
  python main.py --livelogs → Modo verbose (logs completos en consola)
        """,
    )
    parser.add_argument(
        "--livelogs",
        action="store_true",
        default=False,
        help="Mostrar logs en tiempo real en la consola",
    )
    args = parser.parse_args()

    # Bloquear doble instancia
    if not _acquire_lock():
        print(f"\n  ⚠️  Jada ya está corriendo (PID en {PIDFILE}).")
        print("  Detén la instancia anterior con Ctrl+C antes de arrancar una nueva.\n")
        sys.exit(1)

    setup_logging(args.livelogs)
    print_banner(args.livelogs)

    try:
        asyncio.run(main(args.livelogs))
    except KeyboardInterrupt:
        logging.getLogger("jada").info("👋 Jada detenida.")
        print("\n  👋 Jada detenida.\n")
