"""
tools/weather.py — Consulta meteorológica (clima)
Primario: wttr.in (No API key)
Fallback: Open-Meteo (No API key, geocoding incluido)
"""
import requests
import logging

logger = logging.getLogger(__name__)


def get_weather(location: str = "Medellin") -> dict:
    """
    Obtiene el clima actual de una ubicación específica.
    Por defecto usa Medellin.
    """
    # Try wttr.in first (fast, simple)
    result = _wttr(location)
    if not result.get("error"):
        return result

    logger.info(f"wttr.in falló, usando Open-Meteo para {location}")
    # Fallback: Open-Meteo
    return _open_meteo(location)


def _wttr(location: str) -> dict:
    """Clima vía wttr.in."""
    try:
        url = f"https://wttr.in/{location}?format=j1"
        response = requests.get(url, timeout=8, headers={"User-Agent": "curl/7.68"})

        if response.status_code != 200:
            return {"error": f"wttr.in error {response.status_code}"}

        data = response.json()
        current = data.get("current_condition", [{}])[0]
        weather_desc = current.get("weatherDesc", [{}])[0].get("value", "")

        return {
            "location": location,
            "temperature_C": current.get("temp_C", ""),
            "feels_like_C": current.get("FeelsLikeC", ""),
            "humidity_percent": current.get("humidity", ""),
            "description": weather_desc,
            "wind_kmh": current.get("windspeedKmph", ""),
            "observation_time": current.get("observation_time", ""),
        }
    except Exception as e:
        return {"error": str(e)}


# Weather code mapping (WMO codes → Spanish descriptions)
_WMO_CODES = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado",
    3: "Nublado", 45: "Neblina", 48: "Neblina con escarcha",
    51: "Llovizna ligera", 53: "Llovizna moderada", 55: "Llovizna densa",
    61: "Lluvia ligera", 63: "Lluvia moderada", 65: "Lluvia fuerte",
    71: "Nieve ligera", 73: "Nieve moderada", 75: "Nieve fuerte",
    80: "Chubascos ligeros", 81: "Chubascos moderados", 82: "Chubascos fuertes",
    95: "Tormenta eléctrica", 96: "Tormenta con granizo ligero", 99: "Tormenta con granizo",
}


def _open_meteo(location: str) -> dict:
    """Clima vía Open-Meteo (fallback, sin API key)."""
    try:
        # Step 1: Geocode the location name → lat/lon
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "es"},
            timeout=8,
        )
        geo.raise_for_status()
        results = geo.json().get("results", [])
        if not results:
            return {"error": f"No encontré la ubicación: {location}"}

        place = results[0]
        lat, lon = place["latitude"], place["longitude"]
        resolved_name = place.get("name", location)
        country = place.get("country", "")

        # Step 2: Get current weather
        wx = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=8,
        )
        wx.raise_for_status()
        current = wx.json().get("current", {})

        code = current.get("weather_code", -1)
        description = _WMO_CODES.get(code, f"Código {code}")

        return {
            "location": f"{resolved_name}, {country}",
            "temperature_C": str(current.get("temperature_2m", "")),
            "feels_like_C": str(current.get("apparent_temperature", "")),
            "humidity_percent": str(current.get("relative_humidity_2m", "")),
            "description": description,
            "wind_kmh": str(current.get("wind_speed_10m", "")),
            "source": "Open-Meteo",
        }
    except Exception as e:
        return {"error": f"Error buscando el clima para {location}: {str(e)}"}
