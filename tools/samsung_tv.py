"""
Samsung Smart TV Control via SmartThings API
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

SMARTTHINGS_TOKEN = os.getenv("SMARTTHINGS_TOKEN")
SMARTTHINGS_CLIENT_ID = os.getenv("SMARTTHINGS_CLIENT_ID")
SMARTTHINGS_CLIENT_SECRET = os.getenv("SMARTTHINGS_CLIENT_SECRET")
SMARTTHINGS_REFRESH_TOKEN = os.getenv("SMARTTHINGS_REFRESH_TOKEN")

BASE_URL = "https://api.smartthings.com/v1"
TOKEN_URL = "https://api.smartthings.com/oauth/token"


def refresh_smartthings_token():
    """
    Refresca el access token usando el refresh token.
    Actualiza automáticamente el archivo .env con los nuevos valores.
    """
    global SMARTTHINGS_TOKEN, SMARTTHINGS_REFRESH_TOKEN
    
    if not all([SMARTTHINGS_CLIENT_ID, SMARTTHINGS_CLIENT_SECRET, SMARTTHINGS_REFRESH_TOKEN]):
        return False

    import base64
    auth_str = f"{SMARTTHINGS_CLIENT_ID}:{SMARTTHINGS_CLIENT_SECRET}"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": SMARTTHINGS_REFRESH_TOKEN
    }

    try:
        response = requests.post(TOKEN_URL, headers=headers, data=data, timeout=15)
        if response.status_code == 200:
            tokens = response.json()
            new_access = tokens.get("access_token")
            new_refresh = tokens.get("refresh_token")
            
            if new_access:
                _update_env_file("SMARTTHINGS_TOKEN", new_access)
                SMARTTHINGS_TOKEN = new_access
            
            if new_refresh:
                _update_env_file("SMARTTHINGS_REFRESH_TOKEN", new_refresh)
                SMARTTHINGS_REFRESH_TOKEN = new_refresh
                
            return True
    except Exception as e:
        print(f"Error refrescando token: {e}")
    return False


def _update_env_file(key, value):
    """Actualiza una variable en el archivo .env de forma segura."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r") as f:
        lines = f.readlines()

    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    
    if not found:
        new_lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)


def get_headers():
    """Headers para la API de SmartThings"""
    return {
        "Authorization": f"Bearer {SMARTTHINGS_TOKEN}",
        "Content-Type": "application/json"
    }


def list_devices():
    """Lista todos los dispositivos disponibles"""
    if not SMARTTHINGS_TOKEN:
        return {"error": "SMARTTHINGS_TOKEN no configurado en .env"}

    try:
        response = requests.get(
            f"{BASE_URL}/devices",
            headers=get_headers(),
            timeout=10,
        )
        if response.status_code == 401:
            # Token expirado, intentar refresco
            if refresh_smartthings_token():
                response = requests.get(
                    f"{BASE_URL}/devices",
                    headers=get_headers(),
                    timeout=10,
                )

        if response.status_code != 200:
            return {"error": f"SmartThings API error {response.status_code}: {response.text[:200]}"}
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def get_device_id(device_name=None):
    """Obtiene el ID del dispositivo por nombre"""
    devices = list_devices()

    if "error" in devices:
        return None

    device_list = devices.get("items", [])

    if not device_list:
        return None

    if device_name:
        for device in device_list:
            if device_name.lower() in device.get("label", "").lower() or \
               device_name.lower() in device.get("name", "").lower() or \
               device_name == device.get("deviceId"):
                return device.get("deviceId")

    # Buscar por tipo TV
    tv_types = ["tv", "samsung tv", "samsung ocf tv", "samsung smart tv", "ocf"]
    for device in device_list:
        device_type = device.get("deviceTypeName", "").lower()
        device_label = device.get("label", "").lower()
        if any(t in device_type or t in device_label for t in tv_types):
            return device.get("deviceId")

    # Fallback: devuelve el primer dispositivo disponible
    return device_list[0].get("deviceId") if device_list else None


def tv_control(action: str, device_name: str = None):
    """
    Controla el TV Samsung
    
    Args:
        action: "on", "off", "up", "down", "mute", "unmute"
        device_name: Nombre del dispositivo (opcional)
    
    Returns:
        dict: Respuesta de la API
    """
    if not SMARTTHINGS_TOKEN:
        return {"success": False, "error": "SMARTTHINGS_TOKEN no configurado en .env"}
    
    device_id = get_device_id(device_name)
    
    if not device_id:
        return {"success": False, "error": "No se encontró el dispositivo"}
    
    # Map de comandos para SmartThings
    command_map = {
        # Power — switch estándar, confirmado en capabilities
        "on":      {"capability": "switch",                  "command": "on",             "args": []},
        "off":     {"capability": "switch",                  "command": "off",            "args": []},

        # Volumen
        "up":      {"capability": "audioVolume",  "command": "volumeUp",   "args": []},
        "down":    {"capability": "audioVolume",  "command": "volumeDown", "args": []},

        # Mute
        "mute":    {"capability": "audioMute",    "command": "mute",       "args": []},
        "unmute":  {"capability": "audioMute",    "command": "unmute",     "args": []},

        # Control remoto
        "ok":      {"capability": "samsungvd.remoteControl", "command": "sendKey",        "args": ["OK"]},
        "back":    {"capability": "samsungvd.remoteControl", "command": "sendKey",        "args": ["BACK"]},
        "home":    {"capability": "samsungvd.remoteControl", "command": "sendKey",        "args": ["HOME"]},
        "menu":    {"capability": "samsungvd.remoteControl", "command": "sendKey",        "args": ["MENU"]},
        "source":  {"capability": "samsungvd.remoteControl", "command": "sendKey",        "args": ["SOURCE"]},

        # Entrada HDMI
        "hdmi1":   {"capability": "samsungvd.mediaInputSource", "command": "setInputSource", "args": ["HDMI1"]},
        "hdmi2":   {"capability": "samsungvd.mediaInputSource", "command": "setInputSource", "args": ["HDMI2"]},
        "hdmi3":   {"capability": "samsungvd.mediaInputSource", "command": "setInputSource", "args": ["HDMI3"]},
    }
    
    if action.lower() not in command_map:
        return {"success": False, "error": f"Acción '{action}' no válida. Usa: {', '.join(command_map)}"}
    
    cap = command_map[action.lower()]
    payload = {
        "commands": [
            {
                "component": "main",
                "capability": cap["capability"],
                "command": cap["command"],
                **({"arguments": cap["args"]} if cap["args"] else {}),
            }
        ]
    }

    try:
        response = requests.post(
            f"{BASE_URL}/devices/{device_id}/commands",
            headers=get_headers(),
            json=payload
        )
        
        if response.status_code == 401:
            if refresh_smartthings_token():
                response = requests.post(
                    f"{BASE_URL}/devices/{device_id}/commands",
                    headers=get_headers(),
                    json=payload
                )

        if response.status_code in [200, 202]:
            action_messages = {
                "on": "encendido",
                "off": "apagado",
                "up": "subido volumen",
                "down": "bajado volumen",
                "mute": "silenciado",
                "unmute": "dessilenciado",
                "ok": "botón OK presionado",
                "back": "botón ATRÁS presionado",
                "home": "botón HOME presionado",
                "menu": "botón MENÚ presionado",
                "source": "botón SOURCE presionado",
                "hdmi1": "cambiado a HDMI 1",
                "hdmi2": "cambiado a HDMI 2",
                "hdmi3": "cambiado a HDMI 3",
            }
            return {
                "success": True,
                "action": action,
                "device_id": device_id,
                "message": f"TV {action_messages.get(action, action)} correctamente"
            }
        else:
            return {
                "success": False,
                "error": response.text
            }
            
    except Exception as e:
        return {"success": False, "error": str(e)}


def tv_status(device_name: str = None):
    """Obtiene el estado actual del TV"""
    if not SMARTTHINGS_TOKEN:
        return {"error": "SMARTTHINGS_TOKEN no configurado en .env"}
    
    device_id = get_device_id(device_name)
    
    if not device_id:
        return {"success": False, "error": "No se encontró el dispositivo"}
    
    try:
        response = requests.get(
            f"{BASE_URL}/devices/{device_id}/status",
            headers=get_headers()
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Uso: python samsung_tv.py <on|off|status|list> [nombre_dispositivo]")
        sys.exit(1)
    
    action = sys.argv[1].lower()
    device_name = sys.argv[2] if len(sys.argv) > 2 else None
    
    if action == "list":
        result = list_devices()
    elif action == "status":
        result = tv_status(device_name)
    elif action in ["on", "off", "up", "down", "mute", "unmute"]:
        result = tv_control(action, device_name)
    else:
        print(f"Acción '{action}' no válida")
        sys.exit(1)
    
    print(result)