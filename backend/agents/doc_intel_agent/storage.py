"""
storage.py — Conexión a Cloudflare R2 para almacenamiento de PDFs.

¿Por qué R2 en vez de guardar los PDFs en el servidor?
En Render (y cualquier plataforma cloud con contenedores) el sistema de
archivos es efímero — se borra al redeploy. Si guardas los PDFs en disco,
los pierdes cada vez que el servidor se reinicia.

R2 es almacenamiento persistente externo. El PDF vive ahí para siempre,
independientemente de lo que le pase al servidor.

¿Por qué boto3 si R2 es de Cloudflare y no de Amazon?
R2 implementa la misma API que S3 de Amazon. Boto3 es el cliente oficial
de AWS para Python, pero funciona con cualquier servicio compatible con S3
— solo cambiando el endpoint_url. Esto es una decisión de Cloudflare para
aprovechar el enorme ecosistema de herramientas de S3.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv(override=False)

# ── Cliente R2 ──────────────────────────────────────────────────────────────


def get_r2_client():
    """
    Crea y devuelve un cliente boto3 configurado para Cloudflare R2.

    La diferencia con S3 normal es el endpoint_url — apunta a R2 en vez
    de a los servidores de Amazon.

    region_name="auto" le dice a R2 que elija automáticamente la región
    más cercana al usuario.
    """
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "doc-intel-documents")


# ── Operaciones ─────────────────────────────────────────────────────────────


def upload_pdf(file_bytes: bytes, original_filename: str) -> str:
    """
    Sube un PDF a R2 y devuelve su clave (key) en el bucket.

    ¿Qué es una key?
    En R2/S3 no hay carpetas reales — solo "keys" que son strings.
    Una key como "pdfs/2026/contrato.pdf" parece una ruta de carpetas
    pero en realidad es un string plano. Los clientes la muestran como
    carpetas para hacerlo más legible.

    Usamos UUID para evitar colisiones — si dos usuarios suben "contrato.pdf"
    no se sobreescriben.

    Args:
        file_bytes: contenido binario del PDF
        original_filename: nombre original del archivo

    Returns:
        key del archivo en R2 (ej: "pdfs/abc123-contrato.pdf")
    """
    client = get_r2_client()

    # Generamos una key única combinando UUID + nombre original
    unique_id = str(uuid.uuid4())[:8]
    safe_filename = Path(original_filename).name  # elimina rutas maliciosas
    key = f"pdfs/{unique_id}-{safe_filename}"

    client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType="application/pdf",
    )

    return key


def download_pdf(key: str) -> bytes:
    """
    Descarga un PDF de R2 por su key.

    Returns:
        Contenido binario del PDF.

    Raises:
        FileNotFoundError: si el archivo no existe en R2.
    """
    client = get_r2_client()

    try:
        response = client.get_object(Bucket=BUCKET_NAME, Key=key)
        return response["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            raise FileNotFoundError(f"PDF not found in R2: {key}") from e
        raise


def delete_pdf(key: str) -> bool:
    """
    Elimina un PDF de R2.

    Returns:
        True si se eliminó correctamente.
    """
    client = get_r2_client()
    client.delete_object(Bucket=BUCKET_NAME, Key=key)
    return True


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """
    Genera una URL temporal para acceder al PDF directamente.

    ¿Para qué sirve una presigned URL?
    En vez de descargar el PDF al servidor y luego mandarlo al cliente,
    generamos una URL firmada que el cliente puede usar para descargar
    directamente desde R2. Más eficiente y no consume ancho de banda
    del servidor.

    Args:
        key: clave del archivo en R2
        expires_in: segundos hasta que expira la URL (default: 1 hora)

    Returns:
        URL temporal de acceso directo al PDF.
    """
    client = get_r2_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )


def list_pdfs() -> list[dict]:
    """
    Lista todos los PDFs almacenados en el bucket.

    Returns:
        Lista de dicts con key, size y last_modified de cada archivo.
    """
    client = get_r2_client()

    response = client.list_objects_v2(
        Bucket=BUCKET_NAME,
        Prefix="pdfs/",
    )

    files = []
    for obj in response.get("Contents", []):
        files.append(
            {
                "key": obj["Key"],
                "size_kb": round(obj["Size"] / 1024, 1),
                "last_modified": str(obj["LastModified"]),
            }
        )

    return files
