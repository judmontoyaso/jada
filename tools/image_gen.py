import os
import base64
import requests
import logging
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger("jada.image_gen")

def generate_image(prompt: str, aspect_ratio: str = "1:1") -> Dict[str, Any]:
    """
    Genera una imagen usando NVIDIA NIM Stable Diffusion 3 Medium.
    
    Args:
        prompt: Descripción de la imagen a generar.
        aspect_ratio: Relación de aspecto ("1:1", "16:9", "21:9", "2:3", "3:2", "4:5", "5:4", "9:16", "9:21").
        
    Returns:
        Dict con 'success', 'file_path' y 'message'.
    """
    api_key = os.getenv("NVIDIA_SD3_API_KEY")
    invoke_url = os.getenv("IMAGE_GEN_URL", "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-3-medium")
    
    if not api_key:
        return {"success": False, "message": "NVIDIA_SD3_API_KEY no configurada."}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    payload = {
        "prompt": prompt,
        "cfg_scale": 5,
        "aspect_ratio": aspect_ratio,
        "seed": 0,
        "steps": 50,
        "negative_prompt": ""
    }

    try:
        logger.info(f"🎨 Generando imagen: '{prompt}' (AI: {aspect_ratio})")
        response = requests.post(invoke_url, headers=headers, json=payload)
        response.raise_for_status()
        
        response_data = response.json()
        
        # El NIM suele devolver b64_json o url. Stable Diffusion 3 en NIM devuelve b64_json.
        image_b64 = response_data.get("image")
        if not image_b64:
            return {"success": False, "message": "No se recibió imagen en la respuesta de la API."}
        
        # Guardar imagen temporalmente
        output_dir = Path("tmp/images")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        import time
        filename = f"gen_{int(time.time())}.png"
        file_path = output_dir / filename
        
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(image_b64))
            
        logger.info(f"✅ Imagen guardada en: {file_path}")
        return {
            "success": True, 
            "file_path": str(file_path.absolute()), 
            "message": "Imagen generada con éxito."
        }
        
    except Exception as e:
        logger.error(f"❌ Error generando imagen: {e}")
        return {"success": False, "message": f"Error en la API de imagen: {str(e)}"}
