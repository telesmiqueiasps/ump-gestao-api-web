import logging
import re
import boto3
from botocore.exceptions import ClientError
from app.core.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)


def _get_client():
    key_id = settings.b2_key_id or ""
    logger.info(
        "B2 client init - key_id prefix: %s... | endpoint: %s | bucket: %s",
        key_id[:8],
        settings.b2_endpoint_url,
        settings.b2_bucket_name,
    )
    # ATENÇÃO: aws_access_key_id deve ser o "keyID" da Application Key
    # (começa com "005..."), NÃO o accountId da conta.
    # aws_secret_access_key deve ser a "applicationKey" (chave longa gerada).
    return boto3.client(
        "s3",
        endpoint_url=settings.b2_endpoint_url,
        aws_access_key_id=settings.b2_key_id,
        aws_secret_access_key=settings.b2_application_key,
        region_name="us-west-004",
    )


def _download_base() -> str:
    """Deriva a base de URL de download público a partir do endpoint S3.

    Exemplos:
      https://s3.us-east-005.backblazeb2.com  →  https://f005.backblazeb2.com/file/<bucket>
      https://s3.us-west-004.backblazeb2.com  →  https://f004.backblazeb2.com/file/<bucket>
      https://s3.eu-central-003.backblazeb2.com → https://f003.backblazeb2.com/file/<bucket>
    """
    match = re.search(r'(\w+)-(\w+)-(\d+)', settings.b2_endpoint_url)
    region_num = match.group(3) if match else "005"
    return f"https://f{region_num}.backblazeb2.com/file/{settings.b2_bucket_name}"


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
    return f"{_download_base()}/{key}"


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
        # Lista todas as versões do arquivo
        response = client.list_object_versions(
            Bucket=settings.b2_bucket_name,
            Prefix=key
        )

        # Exclui todas as versões (Versions) e markers de exclusão (DeleteMarkers)
        versions = response.get('Versions', [])
        delete_markers = response.get('DeleteMarkers', [])

        all_objects = [
            {'Key': v['Key'], 'VersionId': v['VersionId']}
            for v in versions
        ] + [
            {'Key': d['Key'], 'VersionId': d['VersionId']}
            for d in delete_markers
        ]

        logger.info(f"Deletando arquivo do B2 - key: {key} - {len(all_objects)} versão(ões)")

        if all_objects:
            client.delete_objects(
                Bucket=settings.b2_bucket_name,
                Delete={'Objects': all_objects}
            )

        return True
    except Exception as e:
        logger.error(f"Erro ao deletar arquivo do B2: {e}")
        return False


def delete_folder(prefix: str) -> bool:
    client = _get_client()
    try:
        # Lista todas as versões de todos os objetos com esse prefixo
        response = client.list_object_versions(
            Bucket=settings.b2_bucket_name,
            Prefix=prefix
        )

        versions = response.get('Versions', [])
        delete_markers = response.get('DeleteMarkers', [])

        all_objects = [
            {'Key': v['Key'], 'VersionId': v['VersionId']}
            for v in versions
        ] + [
            {'Key': d['Key'], 'VersionId': d['VersionId']}
            for d in delete_markers
        ]

        logger.info(f"Deletando pasta do B2 - prefix: {prefix} - {len(all_objects)} objeto(s)")

        if not all_objects:
            return True

        # Exclui tudo de uma vez
        client.delete_objects(
            Bucket=settings.b2_bucket_name,
            Delete={'Objects': all_objects}
        )

        return True
    except Exception as e:
        logger.error(f"Erro ao deletar pasta do B2: {e}")
        return False