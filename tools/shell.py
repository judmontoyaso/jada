"""
tools/shell.py — Ejecutar comandos del sistema de forma segura
"""
import asyncio
import os
import re
from dotenv import load_dotenv

load_dotenv()

# Comandos peligrosos que están bloqueados
_RAW_BLOCKED = os.getenv(
    "BLOCKED_COMMANDS", 
    "rm -rf,format,del /f,shutdown,mkfs,chmod 777,chown,sudo su,passwd"
)
BLOCKED_COMMANDS = [c.strip().lower() for c in _RAW_BLOCKED.split(",") if c.strip()]

# Patrones peligrosos adicionales (regex)
DANGEROUS_PATTERNS = [
    r'[;&|`$]',  # Shell metacharacters
    r'\.\.\/',   # Path traversal
    r'\>\s*\>',  # Redirects peligrosos
    r'\$\(',     # Command substitution
]


async def run_command(command: str, timeout: int = 30, user: str = "unknown") -> dict:
    """
    Ejecuta un comando de shell de forma segura.
    
    Args:
        command: Comando a ejecutar
        timeout: Segundos máximo de ejecución
        user: Usuario que pidió el comando (para logs)
    
    Returns:
        dict con stdout, stderr, returncode, blocked
    """
    # 1. Verificar longitud máxima
    if len(command) > int(os.getenv("MAX_INPUT_LENGTH", "10000")):
        return {
            "stdout": "",
            "stderr": "❌ Error: entrada demasiado larga",
            "returncode": -1,
            "blocked": True,
        }
    
    # 2. Verificar patrones peligrosos (regex)
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return {
                "stdout": "",
                "stderr": f"❌ Patrón peligroso detectado: '{pattern}'",
                "returncode": -1,
                "blocked": True,
            }
    
    # 3. Verificar comandos bloqueados
    cmd_lower = command.lower().strip()
    words = cmd_lower.split()
    
    for blocked in BLOCKED_COMMANDS:
        blocked_clean = blocked.strip().lower()
        # Verificar tanto frases completas como palabras individuales
        if (blocked_clean in cmd_lower or  # "rm -rf" en comando completo
            blocked_clean in words):        # "rm" como palabra individual
            return {
                "stdout": "",
                "stderr": f"❌ Comando bloqueado: '{blocked}'",
                "returncode": -1,
                "blocked": True,
            }
    
    # 4. Verificar si usuario está bloqueado
    blocked_users = os.getenv("BLOCKED_USERS", "").split(",")
    if user.strip().lower() in [u.strip().lower() for u in blocked_users if u.strip()]:
        return {
            "stdout": "",
            "stderr": "❌ Usuario bloqueado",
            "returncode": -1,
            "blocked": True,
        }
    
    try:
        # Crear proceso con restricciones
        if os.name == "nt":
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True,
                limit=1024 * 1024,  # 1MB max output
            )
        else:
            # En Unix, usar bash con comando limitado
            proc = await asyncio.create_subprocess_shell(
                f"exec {command}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                executable="/bin/bash",
                limit=1024 * 1024,  # 1MB max output
            )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )

        return {
            "stdout": stdout.decode("utf-8", errors="replace").strip()[:50000],  # Limitar output
            "stderr": stderr.decode("utf-8", errors="replace").strip()[:5000],
            "returncode": proc.returncode,
            "blocked": False,
        }

    except asyncio.TimeoutError:
        return {
            "stdout": "",
            "stderr": f"⏱️ Timeout: comando excedió {timeout} segundos",
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
