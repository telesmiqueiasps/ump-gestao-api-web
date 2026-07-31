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