"""
tools/shell.py — Ejecutar comandos del sistema de forma segura
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Comandos peligrosos que están bloqueados
_RAW_BLOCKED = os.getenv("BLOCKED_COMMANDS", "rm -rf,format,del /f,shutdown,mkfs")
BLOCKED_COMMANDS = [c.strip().lower() for c in _RAW_BLOCKED.split(",") if c.strip()]


async def run_command(command: str, timeout: int = 30) -> dict:
    """
    Ejecuta un comando de shell y retorna stdout, stderr y código de salida.
    Bloquea comandos peligrosos definidos en BLOCKED_COMMANDS.
    """
    cmd_lower = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return {
                "stdout": "",
                "stderr": f"❌ Comando bloqueado por seguridad: '{blocked}'",
                "returncode": -1,
                "blocked": True,
            }

    try:
        # En Windows usamos PowerShell, en Unix usamos bash
        if os.name == "nt":
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                executable="/bin/bash",
            )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )

        return {
            "stdout": stdout.decode("utf-8", errors="replace").strip(),
            "stderr": stderr.decode("utf-8", errors="replace").strip(),
            "returncode": proc.returncode,
            "blocked": False,
        }

    except asyncio.TimeoutError:
        return {
            "stdout": "",
            "stderr": f"⏱️ Timeout: el comando tardó más de {timeout} segundos.",
            "returncode": -1,
            "blocked": False,
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Error ejecutando comando: {str(e)}",
            "returncode": -1,
            "blocked": False,
        }
