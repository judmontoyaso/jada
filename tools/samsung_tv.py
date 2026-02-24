"""
Samsung Smart TV Control via SmartThings API
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

SMARTTHINGS_TOKEN = os.getenv("SMARTTHINGS_TOKEN")
BASE_URL = "https://api.smartthings.com/v1"


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
            headers=get_headers()
        )
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
               device_name.lower() in device.get("name", "").lower():
                return device.get("deviceId")
    
    # Si no se especifica nombre, devuelve el primer TV encontrado
    for device in device_list:
        if device.get("deviceTypeName", "").lower() in ["tv", "samsung tv", "samsung ocf tv"]:
            return device.get("deviceId")
    
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
    
    # Map de comandos para SmartThings usando execute capability
    commands = {
        "on": {
            "commands": [
                {
                    "capability": "execute",
                    "command": "execute",
                    "arguments": ["stsa://com.samsung.tv.power.on"]
                }
            ]
        },
        "off": {
            "commands": [
                {
                    "capability": "execute",
                    "command": "execute",
                    "arguments": ["stsa://com.samsung.tv.power.off"]
                }
            ]
        },
        "up": {
            "commands": [
                {
                    "capability": "execute",
                    "command": "execute",
                    "arguments": ["stsa://com.samsung.tv.volume.up"]
                }
            ]
        },
        "down": {
            "commands": [
                {
                    "capability": "execute",
                    "command": "execute",
                    "arguments": ["stsa://com.samsung.tv.volume.down"]
                }
            ]
        },
        "mute": {
            "commands": [
                {
                    "capability": "execute",
                    "command": "execute",
                    "arguments": ["stsa://com.samsung.tv.audio.mute"]
                }
            ]
        },
        "unmute": {
            "commands": [
                {
                    "capability": "execute",
                    "command": "execute",
                    "arguments": ["stsa://com.samsung.tv.audio.unmute"]
                }
            ]
        }
    }
    
    if action.lower() not in commands:
        return {"success": False, "error": f"Acción '{action}' no válida. Usa 'on', 'off', 'up', 'down', 'mute', 'unmute'"}
    
    try:
        response = requests.post(
            f"{BASE_URL}/devices/{device_id}/commands",
            headers=get_headers(),
            json=commands[action.lower()]
        )
        
        if response.status_code in [200, 202]:
            action_messages = {
                "on": "encendido",
                "off": "apagado",
                "up": "subido volumen",
                "down": "bajado volumen",
                "mute": "silenciado",
                "unmute": "dessilenciado"
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