"""
tools/shell.py — Ejecutar comandos del sistema de forma segura (WHITELIST MODE)
"""
import asyncio
import os
import re
from dotenv import load_dotenv

load_dotenv()

# Whitelist de comandos seguros (solo estos se permiten)
_SAFE_COMMANDS = os.getenv(
    "SAFE_COMMANDS",
    "echo,ls,pwd,cat,head,tail,grep,find,date,whoami,wc,uniq,sort,tr,cut,awk,sed"
)
SAFE_COMMANDS = [c.strip().lower() for c in _SAFE_COMMANDS.split(",") if c.strip()]

# Comandos que siempre están bloqueados (fallback de seguridad)
BLOCKED_COMMANDS = [
    "rm -rf", "format", "del /f", "shutdown", "mkfs",
    "chmod 777", "chown", "sudo su", "passwd", "wget", "curl"
]

# Patrones peligrosos que siempre se bloquean
CRITICAL_PATTERNS = [
    r'\.\.\/',   # Path traversal
    r'\>\s*\>',  # Redirect overwrite
    r'\$\(',     # Command substitution
]


async def run_command(command: str, timeout: int = 30, user: str = "unknown") -> dict:
    """
    Ejecuta un comando de shell de forma segura (WHITELIST MODE).
    
    Solo permite comandos en SAFE_COMMANDS. Todos los demás son bloqueados.
    
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
    
    # 2. Verificar patrones críticos (siempre bloqueados)
    for pattern in CRITICAL_PATTERNS:
        if re.search(pattern, command):
            return {
                "stdout": "",
                "stderr": f"❌ Patrón crítico bloqueado: '{pattern}'",
                "returncode": -1,
                "blocked": True,
            }
    
    # 3. Verificar si es un comando seguro (WHITELIST)
    cmd_lower = command.lower().strip()
    words = cmd_lower.split()
    
    # El primer comando debe estar en la whitelist
    if not words:
        return {
            "stdout": "",
            "stderr": "❌ Comando vacío",
            "returncode": -1,
            "blocked": True,
        }
    
    first_cmd = words[0]
    
    # Verificar contra whitelist
    if first_cmd not in SAFE_COMMANDS:
        # Verificar también contra blocked commands (fallback)
        is_blocked = any(blocked in cmd_lower for blocked in BLOCKED_COMMANDS)
        if is_blocked:
            return {
                "stdout": "",
                "stderr": f"❌ Comando bloqueado por seguridad: '{first_cmd}'",
                "returncode": -1,
                "blocked": True,
            }
        return {
            "stdout": "",
            "stderr": f"❌ Comando no permitido: '{first_cmd}'. Comandos seguros: {', '.join(SAFE_COMMANDS)}",
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
                limit=1024 * 1024,
            )
        else:
            # En Unix, usar bash
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                executable="/bin/bash",
                limit=1024 * 1024,
            )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )

        return {
            "stdout": stdout.decode("utf-8", errors="replace").strip()[:50000],
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
