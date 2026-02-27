"""
tools/weather.py — Consulta meteorológica (clima) usando wttr.in (No API key needed)
"""
import requests
import json

def get_weather(location: str = "Medellin") -> dict:
    """
    Obtiene el clima actual de una ubicación específica.
    Por defecto usa Medellin.
    """
    try:
        # j1 nos da el payload en json estructurado de alta calidad
        url = f"https://wttr.in/{location}?format=j1"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return {"error": f"Error {response.status_code} desde wttr.in: {response.text[:200]}"}
            
        data = response.json()
        current = data.get("current_condition", [{}])[0]
        weather_description = current.get("weatherDesc", [{}])[0].get("value", "")
        
        return {
            "location": location,
            "temperature_C": current.get("temp_C", ""),
            "feels_like_C": current.get("FeelsLikeC", ""),
            "humidity_percent": current.get("humidity", ""),
            "description": weather_description,
            "wind_kmh": current.get("windspeedKmph", ""),
            "observation_time": current.get("observation_time", "")
        }
        
    except Exception as e:
        return {"error": f"Error buscando el clima para {location}: {str(e)}"}
