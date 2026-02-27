"""
agent/scheduler.py — Scheduler de cronjobs para Jada

Usa croniter (instalado por agno) para parsear expresiones cron
y asyncio para ejecutar tareas programadas sin depender de crontab del sistema.

Cuando vence un cronjob, envía el prompt directamente al agente
(igual que si el usuario lo escribiera en Matrix).
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional

from agno.scheduler.cron import compute_next_run, validate_cron_expr

logger = logging.getLogger("jada.scheduler")

# Archivo de persistencia de cronjobs (reutiliza el del branch cronjobs-gui)
STORAGE_FILE = os.getenv("CRONJOBS_FILE", "cronjobs.json")


class JadaScheduler:
    """
    Scheduler asyncio-nativo para Jada.

    Lee cronjobs desde un JSON, calcula cuándo toca ejecutar cada uno
    usando croniter (via agno.scheduler.cron), y llama al agente
    directamente (no via HTTP) cuando vence el tiempo.

    Intención de uso:
        scheduler = JadaScheduler(agent_callback=agent.run_scheduled)
        await scheduler.start()
    """

    def __init__(self, agent_callback: Callable[[str, str], Coroutine]) -> None:
        """
        Args:
            agent_callback: corrutina que recibe (prompt, room_id) y ejecuta
                            el agente como si fuera un mensaje del usuario.
                            Firma: async def run_scheduled(prompt: str, room_id: str) -> None
        """
        self._callback = agent_callback
        self._agent = None  # seét via set_agent() desde main.py
        self._send_callback = None  # para mensajes directos (heartbeat)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._jobs: Dict[str, dict] = {}
        self._load()

    # ─── Persistencia ────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Carga los cronjobs desde el archivo JSON."""
        if not os.path.exists(STORAGE_FILE):
            self._jobs = {}
            return
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._jobs = data.get("cronjobs", {})
            logger.info(f"📅 Cargados {len(self._jobs)} cronjob(s) desde {STORAGE_FILE}")
        except Exception as e:
            logger.warning(f"No se pudo cargar {STORAGE_FILE}: {e}")
            self._jobs = {}

    def _save(self) -> None:
        """Guarda los cronjobs al archivo JSON."""
        try:
            data = {"version": "2.0", "last_update": datetime.now(timezone.utc).isoformat(), "cronjobs": self._jobs}
            with open(STORAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error guardando cronjobs: {e}")

    # ─── API pública ─────────────────────────────────────────────────────────

    def set_agent(self, agent) -> None:
        """Inyecta referencia al agente (necesaria para heartbeat)."""
        self._agent = agent
        self._send_callback = getattr(agent, '_send_callback', None)

    def add_job(
        self,
        job_id: str,
        name: str,
        cron_expr: str,
        prompt: str,
        room_id: str,
        description: str = "",
        timezone_str: str = "UTC",
        enabled: bool = True,
    ) -> dict:
        """
        Agrega un nuevo cronjob.

        Args:
            job_id: ID único del job
            name: Nombre legible
            cron_expr: Expresión cron estándar ("0 6 * * *" = todos los días a las 6am)
            prompt: Prompt que se enviará al agente cuando venza
            room_id: ID del room de Matrix donde responder
            timezone_str: Timezone (default: UTC)
        """
        if not validate_cron_expr(cron_expr):
            raise ValueError(f"Expresión cron inválida: '{cron_expr}'")

        # ── Deduplicación: evitar cronjobs idénticos ──────────────────────────
        for existing in self._jobs.values():
            same_expr = existing["cron_expr"] == cron_expr
            same_room = existing["room_id"] == room_id
            same_name = existing["name"].lower().strip() == name.lower().strip()
            if same_expr and same_room and same_name:
                logger.warning(f"⚠️ Cronjob duplicado detectado: '{name}' ya existe (id={existing['id']}). Ignorando.")
                existing["_duplicate"] = True
                return existing  # Retorna el existente sin crear uno nuevo
        # ─────────────────────────────────────────────────────────────────────

        next_run = compute_next_run(cron_expr, timezone_str)

        job = {
            "id": job_id,
            "name": name,
            "cron_expr": cron_expr,
            "prompt": prompt,
            "room_id": room_id,
            "description": description,
            "timezone": timezone_str,
            "enabled": enabled,
            "next_run_at": next_run,
            "last_run_at": None,
            "last_status": None,
            "created_at": int(time.time()),
        }
        self._jobs[job_id] = job
        self._save()
        logger.info(f"✅ Cronjob '{name}' creado (expr={cron_expr}, next={datetime.fromtimestamp(next_run, tz=timezone.utc)})")
        return job

    def update_job(self, job_id: str, **kwargs: Any) -> Optional[dict]:
        """Actualiza campos de un cronjob existente."""
        if job_id not in self._jobs:
            return None
        job = self._jobs[job_id]
        # Si cambia la expresión, recalcular next_run
        if "cron_expr" in kwargs:
            if not validate_cron_expr(kwargs["cron_expr"]):
                raise ValueError(f"Expresión cron inválida: '{kwargs['cron_expr']}'")
            kwargs["next_run_at"] = compute_next_run(kwargs["cron_expr"], job.get("timezone", "UTC"))
        job.update(kwargs)
        self._save()
        return job

    def delete_job(self, job_id: str) -> bool:
        """Elimina un cronjob."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save()
            return True
        return False

    def get_job(self, job_id: str) -> Optional[dict]:
        """Obtiene un cronjob por ID."""
        return self._jobs.get(job_id)

    def list_jobs(self, enabled_only: bool = False) -> List[dict]:
        """Lista todos los cronjobs."""
        jobs = list(self._jobs.values())
        if enabled_only:
            jobs = [j for j in jobs if j.get("enabled", True)]
        return jobs

    def get_status(self) -> dict:
        """Retorna el estado del scheduler."""
        return {
            "running": self._running,
            "total_jobs": len(self._jobs),
            "enabled_jobs": sum(1 for j in self._jobs.values() if j.get("enabled")),
            "jobs": [
                {
                    "id": j["id"],
                    "name": j["name"],
                    "cron_expr": j["cron_expr"],
                    "enabled": j.get("enabled", True),
                    "next_run_at": j.get("next_run_at"),
                    "last_run_at": j.get("last_run_at"),
                    "last_status": j.get("last_status"),
                }
                for j in self._jobs.values()
            ],
        }

    # ─── Loop principal ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Inicia el scheduler en background."""
        if self._running:
            logger.warning("Scheduler ya está corriendo")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("🕐 Jada Scheduler iniciado")

    async def stop(self) -> None:
        """Detiene el scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Jada Scheduler detenido")

    async def _loop(self) -> None:
        """Loop principal: cada 30 segundos revisa si algún job debe ejecutarse."""
        POLL_INTERVAL = 30  # segundos entre checks

        while self._running:
            now = int(time.time())
            self._load()  # Re-cargar por si hubo cambios externos

            for job_id, job in list(self._jobs.items()):
                if not job.get("enabled", True):
                    continue

                next_run = job.get("next_run_at")
                if next_run and now >= next_run:
                    asyncio.create_task(self._execute_job(job))

            await asyncio.sleep(POLL_INTERVAL)

    async def _execute_job(self, job: dict) -> None:
        """Ejecuta un cronjob: llama al agente con el prompt del job."""
        job_id = job["id"]
        name = job["name"]
        prompt = job["prompt"]
        room_id = job.get("room_id", "")

        logger.info(f"⏰ Ejecutando cronjob '{name}' (id={job_id})")

        # Actualizar estado a running
        self._jobs[job_id]["last_run_at"] = int(time.time())
        self._jobs[job_id]["last_status"] = "running"

        # Calcular próxima ejecución ANTES de ejecutar (para no perder el slot)
        try:
            next_run = compute_next_run(
                job["cron_expr"],
                job.get("timezone", "UTC"),
            )
            self._jobs[job_id]["next_run_at"] = next_run
        except Exception as e:
            logger.error(f"Error calculando next_run para '{name}': {e}")
            self._jobs[job_id]["last_status"] = "error"
            self._save()
            return

        self._save()

        # Llamar al agente
        try:
            if prompt == "__heartbeat__":
                from agent.heartbeat import run_heartbeat
                llm = getattr(self._agent, 'llm', None)
                send_cb = getattr(self._agent, '_send_callback', None)
                await run_heartbeat(llm=llm, send_callback=send_cb, room_id=room_id)
            else:
                await self._callback(prompt, room_id)
            self._jobs[job_id]["last_status"] = "success"
            logger.info(f"✅ Cronjob '{name}' ejecutado exitosamente")
        except Exception as e:
            self._jobs[job_id]["last_status"] = "error"
            logger.error(f"❌ Error ejecutando cronjob '{name}': {e}")
        finally:
            self._save()


# ─── Instancia global ──────────────────────────────────────────────────────────

_scheduler: Optional[JadaScheduler] = None


def get_scheduler() -> Optional[JadaScheduler]:
    return _scheduler


def init_scheduler(agent_callback: Callable) -> JadaScheduler:
    """Inicializa el scheduler global de Jada."""
    global _scheduler
    _scheduler = JadaScheduler(agent_callback)
    return _scheduler
