"""
tests/test_security.py — Tests de seguridad para Jada

Ejecutar: python -m pytest tests/test_security.py -v
O sin pytest: python tests/test_security.py
"""
import asyncio
import json
import os
import sys
import time

# Fix encoding para Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Shell Blocklist
# ═══════════════════════════════════════════════════════════════════════════════

async def test_shell_blocklist():
    """Verificar que los comandos bloqueados son rechazados."""
    from tools.shell import run_command

    dangerous_commands = [
        "rm -rf /",
        "rm -rf .",
        "format C:",
        "del /f /s /q *",
        "shutdown /s",
        "shutdown -h now",
    ]

    results = []
    for cmd in dangerous_commands:
        result = await run_command(cmd)
        blocked = "error" in result or "bloqueado" in str(result).lower() or "blocked" in str(result).lower()
        results.append({"command": cmd, "blocked": blocked, "result": str(result)[:100]})
        if not blocked:
            print(f"  ❌ FALLO: Comando peligroso NO bloqueado: {cmd}")
        else:
            print(f"  ✅ OK: Comando bloqueado: {cmd}")

    passed = all(r["blocked"] for r in results)
    return {"test": "shell_blocklist", "passed": passed, "results": results}


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: Shell Injection
# ═══════════════════════════════════════════════════════════════════════════════

async def test_shell_injection():
    """Verificar que no se pueden inyectar comandos peligrosos vía separadores."""
    from tools.shell import run_command

    injection_attempts = [
        "echo hello && rm -rf /",
        "echo hello; rm -rf /",
        "echo hello | rm -rf /",
        'echo hello `rm -rf /`',
        "echo hello $(rm -rf /)",
    ]

    results = []
    for cmd in injection_attempts:
        result = await run_command(cmd)
        # El comando debería ser bloqueado o al menos no ejecutar rm -rf
        blocked = "error" in result or "bloqueado" in str(result).lower() or "blocked" in str(result).lower()
        results.append({"command": cmd, "blocked": blocked, "result": str(result)[:100]})
        status = "✅ OK" if blocked else "⚠️ ADVERTENCIA (verificar manualmente)"
        print(f"  {status}: {cmd}")

    # Este test es advisory — depende de la implementación de run_command
    return {"test": "shell_injection", "results": results}


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: File Path Traversal
# ═══════════════════════════════════════════════════════════════════════════════

async def test_file_path_traversal():
    """Verificar que no se pueden leer archivos sensibles del sistema."""
    from tools.files import read_file

    sensitive_paths = [
        "/etc/passwd",
        "/etc/shadow",
        "C:\\Windows\\System32\\config\\SAM",
        "../../.env",
        "../../../etc/passwd",
    ]

    results = []
    for path in sensitive_paths:
        result = await read_file(path)
        has_content = "content" in result and result.get("content", "")
        results.append({
            "path": path,
            "accessible": has_content,
            "result": str(result)[:100]
        })
        if has_content:
            print(f"  ⚠️ ADVERTENCIA: Archivo sensible accesible: {path}")
        else:
            print(f"  ✅ OK: No accesible: {path}")

    return {"test": "file_path_traversal", "results": results}


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4: Tool Schemas Válidos
# ═══════════════════════════════════════════════════════════════════════════════

def test_tool_schemas_valid():
    """Verificar que todos los tool schemas tienen type en cada propiedad."""
    from agent.tools import TOOL_SCHEMAS

    errors = []
    for tool in TOOL_SCHEMAS:
        func = tool.get("function", {})
        name = func.get("name", "unknown")
        params = func.get("parameters", {})
        properties = params.get("properties", {})

        for prop_name, prop_def in properties.items():
            if "type" not in prop_def:
                error = f"Tool '{name}' → propiedad '{prop_name}' sin type"
                errors.append(error)
                print(f"  ❌ {error}")

        # Verificar propiedades de items en arrays
        for prop_name, prop_def in properties.items():
            if prop_def.get("type") == "array" and "items" in prop_def:
                items = prop_def["items"]
                if items.get("type") == "object" and "properties" in items:
                    for item_prop, item_def in items["properties"].items():
                        if "type" not in item_def:
                            error = f"Tool '{name}' → '{prop_name}' → item '{item_prop}' sin type"
                            errors.append(error)
                            print(f"  ❌ {error}")

    if not errors:
        print(f"  ✅ Todos los {len(TOOL_SCHEMAS)} tool schemas son válidos")

    return {
        "test": "tool_schemas_valid",
        "passed": len(errors) == 0,
        "total_tools": len(TOOL_SCHEMAS),
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: Rate Limiting
# ═══════════════════════════════════════════════════════════════════════════════

def test_rate_limiting():
    """Verificar que el rate limiter funciona correctamente."""
    from matrix.client import MatrixBot

    class FakeAgent:
        pass

    bot = MatrixBot(FakeAgent())
    test_user = "@test:example.com"

    # Enviar mensajes dentro del límite
    allowed_count = 0
    for i in range(20):
        if bot._check_rate_limit(test_user):
            allowed_count += 1

    from matrix.client import RATE_LIMIT_PER_MINUTE
    expected = RATE_LIMIT_PER_MINUTE

    passed = allowed_count == expected
    if passed:
        print(f"  ✅ Rate limit funciona: {allowed_count}/{expected} mensajes permitidos")
    else:
        print(f"  ❌ Rate limit fallo: {allowed_count} permitidos, esperados {expected}")

    return {
        "test": "rate_limiting",
        "passed": passed,
        "allowed": allowed_count,
        "expected": expected,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6: Email y Calendar son solo lectura
# ═══════════════════════════════════════════════════════════════════════════════

def test_email_calendar_readonly():
    """Verificar que las tools de email y calendario no exponen operaciones de escritura."""
    from agent.tools import TOOL_SCHEMAS

    email_tools = [t for t in TOOL_SCHEMAS if t["function"]["name"].startswith("email_")]
    calendar_tools = [t for t in TOOL_SCHEMAS if t["function"]["name"].startswith("calendar_")]

    # Verificar que no hay tools de envío/borrado/modificación
    write_keywords = ["send", "delete", "remove", "create", "update", "modify", "compose", "reply", "forward"]

    errors = []
    for tool in email_tools + calendar_tools:
        name = tool["function"]["name"]
        desc = tool["function"].get("description", "").lower()
        for keyword in write_keywords:
            if keyword in name.lower() or keyword in desc:
                error = f"Tool '{name}' parece tener capacidad de escritura ('{keyword}')"
                errors.append(error)
                print(f"  ❌ {error}")

    if not errors:
        print(f"  ✅ Email ({len(email_tools)} tools) y Calendar ({len(calendar_tools)} tools) son solo lectura")

    return {
        "test": "email_calendar_readonly",
        "passed": len(errors) == 0,
        "email_tools": len(email_tools),
        "calendar_tools": len(calendar_tools),
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7: Message Chunking
# ═══════════════════════════════════════════════════════════════════════════════

def test_message_chunking():
    """Verificar que los mensajes largos se dividen correctamente."""
    from matrix.client import MatrixBot

    # Generar un mensaje largo
    long_msg = "Línea de prueba.\n" * 200  # ~3200 chars
    chunks = MatrixBot._split_message(long_msg, 2000)

    passed = True
    for i, chunk in enumerate(chunks):
        if len(chunk) > 2000:
            print(f"  ❌ Chunk {i+1} excede el límite: {len(chunk)} chars")
            passed = False

    if passed:
        print(f"  ✅ Mensaje de {len(long_msg)} chars dividido en {len(chunks)} chunks correctamente")

    return {
        "test": "message_chunking",
        "passed": passed,
        "original_length": len(long_msg),
        "num_chunks": len(chunks),
        "chunk_sizes": [len(c) for c in chunks],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 8: Content null vs empty string
# ═══════════════════════════════════════════════════════════════════════════════

def test_content_null_handling():
    """Verificar que el agente no envía content: '' al LLM."""
    import ast

    agent_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent", "agent.py")
    with open(agent_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Buscar el patrón problemático
    has_empty_string = 'response.content or ""' in content
    has_null = 'response.content or None' in content

    if has_empty_string:
        print('  ❌ Se encontró `response.content or ""` — debería ser `or None`')
    elif has_null:
        print('  ✅ Usa `response.content or None` correctamente')
    else:
        print('  ⚠️ No se encontró el patrón — verificar manualmente')

    return {
        "test": "content_null_handling",
        "passed": has_null and not has_empty_string,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def run_all_tests():
    """Ejecutar todos los tests de seguridad."""
    print("=" * 60)
    print("🛡️  TESTS DE SEGURIDAD — Jada")
    print("=" * 60)

    all_results = []

    tests = [
        ("Shell Blocklist", test_shell_blocklist),
        ("Shell Injection", test_shell_injection),
        ("File Path Traversal", test_file_path_traversal),
        ("Tool Schemas", test_tool_schemas_valid),
        ("Rate Limiting", test_rate_limiting),
        ("Email/Calendar Read-Only", test_email_calendar_readonly),
        ("Message Chunking", test_message_chunking),
        ("Content Null Handling", test_content_null_handling),
    ]

    for name, test_fn in tests:
        print(f"\n{'─' * 40}")
        print(f"🧪 Test: {name}")
        print(f"{'─' * 40}")
        try:
            if asyncio.iscoroutinefunction(test_fn):
                result = await test_fn()
            else:
                result = test_fn()
            all_results.append(result)
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            all_results.append({"test": name, "passed": False, "error": str(e)})

    # Resumen
    print(f"\n{'=' * 60}")
    print("📊 RESUMEN")
    print(f"{'=' * 60}")

    passed = sum(1 for r in all_results if r.get("passed", False))
    failed = sum(1 for r in all_results if r.get("passed") is False)
    advisory = sum(1 for r in all_results if "passed" not in r or r.get("passed") is None)

    print(f"  ✅ Pasaron: {passed}")
    print(f"  ❌ Fallaron: {failed}")
    if advisory:
        print(f"  ⚠️ Advisory: {advisory}")
    print(f"  Total: {len(all_results)}")

    return all_results


if __name__ == "__main__":
    results = asyncio.run(run_all_tests())
