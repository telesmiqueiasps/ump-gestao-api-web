import logging
import re
import threading
from app.core.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

_r2_client_instance = None
_r2_client_lock = threading.Lock()


def _get_client():
    global _r2_client_instance
    if _r2_client_instance is None:
        with _r2_client_lock:
            if _r2_client_instance is None:
                import boto3
                key_id = settings.r2_access_key_id or ""
                logger.info(
                    "R2 client init - key_id prefix: %s... | endpoint: %s | bucket: %s",
                    key_id[:8],
                    settings.r2_endpoint_url,
                    settings.r2_bucket_name,
                )
                _r2_client_instance = boto3.client(
                    "s3",
                    endpoint_url=settings.r2_endpoint_url,
                    aws_access_key_id=settings.r2_access_key_id,
                    aws_secret_access_key=settings.r2_secret_access_key,
                    region_name="auto",
                )
    return _r2_client_instance


def upload_file(contents: bytes, key: str, content_type: str) -> str:
    from botocore.exceptions import ClientError
    client = _get_client()
    try:
        client.put_object(
            Bucket=settings.r2_bucket_name,
            Key=key,
            Body=contents,
            ContentType=content_type,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "desconhecido")
        msg = e.response.get("Error", {}).get("Message", str(e))
        raise RuntimeError(f"Falha ao enviar arquivo para o Cloudflare R2 (código {code}): {msg}") from e
    
    public_domain = settings.r2_public_domain.rstrip('/')
    return f"{public_domain}/{key}"


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    client = _get_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key},
        ExpiresIn=expires_in,
    )
    return url


def delete_file(key: str) -> bool:
    client = _get_client()
    try:
        logger.info(f"Deletando arquivo do R2 - key: {key}")
        client.delete_object(
            Bucket=settings.r2_bucket_name,
            Key=key
        )
        return True
    except Exception as e:
        logger.error(f"Erro ao deletar arquivo do R2: {e}")
        return False


def delete_folder(prefix: str) -> bool:
    client = _get_client()
    try:
        response = client.list_objects_v2(
            Bucket=settings.r2_bucket_name,
            Prefix=prefix
        )

        objects = response.get('Contents', [])
        if not objects:
            return True

        delete_keys = [{'Key': obj['Key']} for obj in objects]
        logger.info(f"Deletando pasta do R2 - prefix: {prefix} - {len(delete_keys)} objeto(s)")

        client.delete_objects(
            Bucket=settings.r2_bucket_name,
            Delete={'Objects': delete_keys}
        )

        return True
    except Exception as e:
        logger.error(f"Erro ao deletar pasta do R2: {e}")
        return False


def resize_image_max_size(image_bytes: bytes, max_size: int = 1200) -> bytes:
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        if width <= max_size and height <= max_size:
            return image_bytes

        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))

        resample_filter = getattr(Image, "Resampling", None)
        if resample_filter is not None:
            filter_type = resample_filter.LANCZOS
        else:
            filter_type = getattr(Image, "ANTIALIAS", Image.BICUBIC)

        img_resized = img.resize((new_width, new_height), filter_type)
        fmt = img.format or "JPEG"
        out_buf = io.BytesIO()
        img_resized.save(out_buf, format=fmt, quality=85)
        return out_buf.getvalue()
    except Exception as e:
        logger.error(f"Erro ao redimensionar imagem: {e}")
        return image_bytes


def get_file_base64(url: str) -> str:
    if not url:
        return None
    match = re.search(
        r'(?:/file/[^/]+/|/)(activities/.+|receipts/.+|logos/.+|reports/.+|pix-qr/.+|signatures/.+)$',
        url
    )
    key = match.group(1) if match else url
    client = _get_client()
    try:
        resp = client.get_object(Bucket=settings.r2_bucket_name, Key=key)
        content_type = resp.get('ContentType', 'image/png')
        body = resp['Body'].read()
        import base64
        return f"data:{content_type};base64,{base64.b64encode(body).decode('utf-8')}"
    except Exception as e:
        logger.error(f"Erro ao obter base64 de {key}: {e}")
        return None


def extract_key_from_url(url: str) -> str | None:
    if not url:
        return None
    public_domain = settings.r2_public_domain.rstrip('/')
    if url.startswith(public_domain):
        return url.replace(f"{public_domain}/", "")
    match = re.search(
        r'(?:members/.+|activities/.+|receipts/.+|logos/.+|reports/.+|pix-qr/.+|signatures/.+)$',
        url
    )
    if match:
        return match.group(0)
    if "http" in url:
        parts = url.split("/")
        return "/".join(parts[3:]) if len(parts) > 3 else parts[-1]
    return url