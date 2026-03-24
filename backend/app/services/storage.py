import boto3
from botocore.exceptions import ClientError
from app.core.config import get_settings

settings = get_settings()


def _get_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.b2_endpoint_url,
        aws_access_key_id=settings.b2_key_id,
        aws_secret_access_key=settings.b2_application_key,
        region_name="us-west-004",
    )


def upload_file(contents: bytes, key: str, content_type: str) -> str:
    client = _get_client()
    try:
        client.put_object(
            Bucket=settings.b2_bucket_name,
            Key=key,
            Body=contents,
            ContentType=content_type,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "desconhecido")
        msg = e.response.get("Error", {}).get("Message", str(e))
        raise RuntimeError(f"Falha ao enviar arquivo para o Backblaze B2 (código {code}): {msg}") from e
    # Retorna URL pública (bucket público) ou pre-signed (bucket privado)
    url = f"{settings.b2_endpoint_url}/file/{settings.b2_bucket_name}/{key}"
    return url


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    client = _get_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.b2_bucket_name, "Key": key},
        ExpiresIn=expires_in,
    )
    return url


def delete_file(key: str) -> bool:
    client = _get_client()
    try:
        client.delete_object(Bucket=settings.b2_bucket_name, Key=key)
        return True
    except ClientError:
        return False