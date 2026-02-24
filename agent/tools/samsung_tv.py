"""
Samsung TV control via SmartThings API
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

SMARTTHINGS_TOKEN = os.getenv("SMARTTHINGS_TOKEN")
BASE_URL = "https://api.smartthings.com/v1"
TV_DEVICE_ID = os.getenv("TV_DEVICE_ID", "8ce46e96-23b7-a84a-3d2c-93bc26bd5960")


def _get_headers():
    """Build headers fresh each call so token is always current."""
    token = os.getenv("SMARTTHINGS_TOKEN")
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def list_devices():
    headers = _get_headers()
    if not headers:
        return {"error": "SMARTTHINGS_TOKEN no configurado en .env"}
    try:
        response = requests.get(f"{BASE_URL}/devices", headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        devices = [
            {
                "deviceId": d.get("deviceId"),
                "name": d.get("label") or d.get("name"),
                "type": d.get("deviceTypeName"),
            }
            for d in data.get("items", [])
        ]
        return {"devices": devices}
    except Exception as e:
        return {"error": str(e)}


def tv_status(device_id: str = TV_DEVICE_ID):
    headers = _get_headers()
    if not headers:
        return {"error": "SMARTTHINGS_TOKEN no configurado en .env"}
    try:
        response = requests.get(
            f"{BASE_URL}/devices/{device_id}/status", headers=headers, timeout=10
        )
        response.raise_for_status()
        components = response.json().get("components", {})
        state = components.get("main", {}).get("switch", {}).get("switch", {}).get("value", "unknown")
        return {"device_id": device_id, "state": state}
    except Exception as e:
        return {"error": str(e)}


def tv_control(device_id: str = TV_DEVICE_ID, command: str = "on"):
    """
    Controla el TV: on, off, up, down, mute, unmute.

    Args:
        device_id: ID del dispositivo (UUID). Por defecto usa TV_DEVICE_ID del .env.
        command: 'on', 'off', 'up', 'down', 'mute', 'unmute'
    """
    headers = _get_headers()
    if not headers:
        return {"error": "SMARTTHINGS_TOKEN no configurado en .env"}

    command_map = {
        "on":     {"capability": "switch",      "command": "on"},
        "off":    {"capability": "switch",      "command": "off"},
        "up":     {"capability": "audioVolume", "command": "volumeUp"},
        "down":   {"capability": "audioVolume", "command": "volumeDown"},
        "mute":   {"capability": "audioMute",   "command": "mute"},
        "unmute": {"capability": "audioMute",   "command": "unmute"},
    }

    if command not in command_map:
        return {"error": f"Comando '{command}' no soportado. Usa: {', '.join(command_map)}"}

    cap = command_map[command]
    payload = {
        "commands": [
            {
                "component": "main",
                "capability": cap["capability"],
                "command": cap["command"],
            }
        ]
    }

    try:
        response = requests.post(
            f"{BASE_URL}/devices/{device_id}/commands",
            headers=headers,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        return {"success": True, "device_id": device_id, "command": command, "result": response.json()}
    except requests.HTTPError as e:
        return {"success": False, "error": e.response.text}
    except Exception as e:
        return {"success": False, "error": str(e)}