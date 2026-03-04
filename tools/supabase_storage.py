"""
tools/supabase_storage.py — Subir, listar, descargar y compartir archivos vía Supabase S3.

Usa el protocolo S3-compatible de Supabase con boto3.
Bucket: jada_filestorage
"""
import os
import logging
import asyncio
import mimetypes
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

S3_ENDPOINT = os.getenv("SUPABASE_S3_ENDPOINT", "")
S3_ACCESS_KEY = os.getenv("SUPABASE_S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("SUPABASE_S3_SECRET_KEY", "")
S3_REGION = os.getenv("SUPABASE_S3_REGION", "us-east-1")
BUCKET = os.getenv("SUPABASE_BUCKET", "jada_filestorage")
PUBLIC_URL = os.getenv("SUPABASE_PUBLIC_URL", "")

# Max file size: 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024


def _get_client():
    """Create a boto3 S3 client for Supabase."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=Config(signature_version="s3v4"),
    )


def _public_url(key: str) -> str:
    """Build public URL for a file."""
    return f"{PUBLIC_URL}/{BUCKET}/{key}"


def _upload_sync(local_path: str, remote_name: Optional[str] = None,
                 folder: str = "") -> dict:
    """Sube un archivo local al bucket de Supabase vía S3."""
    try:
        p = Path(local_path).resolve()
        if not p.exists():
            return {"error": f"Archivo no encontrado: {local_path}"}
        if not p.is_file():
            return {"error": f"No es un archivo: {local_path}"}
        if p.stat().st_size > MAX_FILE_SIZE:
            return {"error": f"Archivo muy grande ({p.stat().st_size / 1024 / 1024:.1f}MB, máx 50MB)"}

        name = remote_name or p.name
        key = f"{folder}/{name}" if folder else name
        mime_type = mimetypes.guess_type(str(p))[0] or "application/octet-stream"

        client = _get_client()
        client.upload_file(
            str(p), BUCKET, key,
            ExtraArgs={"ContentType": mime_type}
        )

        return {
            "success": True,
            "path": key,
            "public_url": _public_url(key),
            "size_bytes": p.stat().st_size,
            "mime_type": mime_type,
        }
    except Exception as e:
        logger.error(f"Error subiendo a Supabase S3: {e}")
        return {"error": f"Error subiendo archivo: {str(e)}"}


def _list_sync(folder: str = "", limit: int = 20) -> dict:
    """Lista archivos en el bucket vía S3."""
    try:
        client = _get_client()
        kwargs = {"Bucket": BUCKET, "MaxKeys": limit}
        if folder:
            kwargs["Prefix"] = folder if folder.endswith("/") else f"{folder}/"

        response = client.list_objects_v2(**kwargs)
        items = response.get("Contents", [])

        files = []
        for item in items:
            key = item["Key"]
            if key.endswith("/"):
                continue  # Skip folder markers
            files.append({
                "name": Path(key).name,
                "path": key,
                "size": item.get("Size", 0),
                "modified": item.get("LastModified", "").isoformat()[:19] if item.get("LastModified") else "",
                "public_url": _public_url(key),
            })

        return {"folder": folder or "/", "files": files, "count": len(files)}
    except Exception as e:
        logger.error(f"Error listando Supabase S3: {e}")
        return {"error": f"Error listando archivos: {str(e)}"}


def _download_sync(remote_path: str, dest_path: Optional[str] = None) -> dict:
    """Descarga un archivo del bucket vía S3."""
    try:
        filename = Path(remote_path).name
        dest = Path(dest_path) if dest_path else Path(f"/opt/jada/tmp/{filename}")
        dest.parent.mkdir(parents=True, exist_ok=True)

        client = _get_client()
        client.download_file(BUCKET, remote_path, str(dest))

        return {
            "success": True,
            "path": str(dest),
            "size_bytes": dest.stat().st_size,
        }
    except Exception as e:
        logger.error(f"Error descargando de Supabase S3: {e}")
        return {"error": f"Error descargando archivo: {str(e)}"}


def _delete_sync(remote_path: str) -> dict:
    """Elimina un archivo del bucket vía S3."""
    try:
        client = _get_client()
        client.delete_object(Bucket=BUCKET, Key=remote_path)
        return {"success": True, "deleted": remote_path}
    except Exception as e:
        logger.error(f"Error eliminando de Supabase S3: {e}")
        return {"error": f"Error eliminando archivo: {str(e)}"}


# ─── Async wrappers ─────────────────────────────────────────────────────────

async def upload_file(local_path: str, remote_name: Optional[str] = None,
                      folder: str = "") -> dict:
    """Sube un archivo local al storage en la nube (Supabase)."""
    return await asyncio.to_thread(_upload_sync, local_path, remote_name, folder)


async def list_files(folder: str = "", limit: int = 20) -> dict:
    """Lista los archivos almacenados en la nube."""
    return await asyncio.to_thread(_list_sync, folder, limit)


async def download_file(remote_path: str, dest_path: Optional[str] = None) -> dict:
    """Descarga un archivo de la nube al servidor local."""
    return await asyncio.to_thread(_download_sync, remote_path, dest_path)


async def delete_file(remote_path: str) -> dict:
    """Elimina un archivo del storage en la nube."""
    return await asyncio.to_thread(_delete_sync, remote_path)
