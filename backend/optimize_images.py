import boto3
import io
import sys
from PIL import Image

# Configurações do Cloudflare R2
R2_ACCESS_KEY_ID = "260b8552eeefbd6ad6b2076f676a2e91"
R2_SECRET_ACCESS_KEY = "cecc37e67473c329b6eacf821e4db5609f66d102b2be3391a4691f8802d76a9b"
R2_ENDPOINT_URL = "https://255c9e32ed75d18f6a1d0b6b9fd49f66.r2.cloudflarestorage.com"
R2_BUCKET_NAME = "ump-gestao-storage"

# Mude para False para aplicar as alterações reais no R2
DRY_RUN = False

def resize_image_bytes(image_bytes, max_size=1200):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        
        # Se a imagem já estiver dentro do tamanho limite, não faz nada
        if width <= max_size and height <= max_size:
            return image_bytes, False
            
        # Calcula nova proporção
        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))
            
        # Determina filtro de redimensionamento
        resample_filter = getattr(Image, "Resampling", None)
        if resample_filter is not None:
            filter_type = resample_filter.LANCZOS
        else:
            filter_type = getattr(Image, "ANTIALIAS", Image.BICUBIC)
            
        img_resized = img.resize((new_width, new_height), filter_type)
        fmt = img.format or "JPEG"
        out_buf = io.BytesIO()
        img_resized.save(out_buf, format=fmt, quality=85)
        return out_buf.getvalue(), True
    except Exception as e:
        print(f"   [!] Erro ao processar imagem com PIL: {e}")
        return image_bytes, False

def run_migration():
    # Inicializa cliente S3/R2
    s3_client = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    
    print("=" * 60)
    print("MIGRAÇÃO DE IMAGENS - CLOUDFLARE R2 OPTIMIZER")
    print(f"Bucket: {R2_BUCKET_NAME}")
    print(f"Modo: {'DRY RUN (Simulação)' if DRY_RUN else 'MIGRAÇÃO REAL (Aplicando alterações)'}")
    print("=" * 60)
    
    paginator = s3_client.get_paginator('list_objects_v2')
    
    total_original_bytes = 0
    total_new_bytes = 0
    images_processed = 0
    images_resized = 0
    
    try:
        pages = paginator.paginate(Bucket=R2_BUCKET_NAME)
        for page in pages:
            contents = page.get('Contents', [])
            if not contents:
                continue
                
            for obj in contents:
                key = obj['Key']
                size_bytes = obj['Size']
                
                # Otimiza apenas imagens nas pastas especificadas
                is_target_folder = any(key.startswith(p) for p in ['activities/', 'receipts/', 'logos/'])
                is_image = key.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
                
                if is_target_folder and is_image:
                    images_processed += 1
                    total_original_bytes += size_bytes
                    print(f"\n[{images_processed}] Encontrada: {key} ({size_bytes / 1024:.1f} KB)")
                    
                    try:
                        # Download da imagem
                        resp = s3_client.get_object(Bucket=R2_BUCKET_NAME, Key=key)
                        img_bytes = resp['Body'].read()
                        content_type = resp.get('ContentType', 'image/jpeg')
                        
                        # Processamento e Redimensionamento
                        resized_bytes, resized = resize_image_bytes(img_bytes, max_size=1200)
                        
                        if resized:
                            images_resized += 1
                            new_size = len(resized_bytes)
                            total_new_bytes += new_size
                            savings = size_bytes - new_size
                            print(f"   -> Redimensionada: {size_bytes / 1024:.1f} KB -> {new_size / 1024:.1f} KB (Economia de {savings / 1024:.1f} KB)")
                            
                            if not DRY_RUN:
                                # Upload da imagem redimensionada sobrescrevendo a antiga
                                s3_client.put_object(
                                    Bucket=R2_BUCKET_NAME,
                                    Key=key,
                                    Body=resized_bytes,
                                    ContentType=content_type,
                                )
                                print("   [+] [SOBRESCRITA] Arquivo otimizado salvo no R2!")
                            else:
                                print("   [o] [DRY RUN] Nenhuma alteração realizada.")
                        else:
                            total_new_bytes += size_bytes
                            print("   -> Imagem já está abaixo do tamanho máximo (1200px) ou não pôde ser redimensionada. Mantida original.")
                            
                    except Exception as e:
                        total_new_bytes += size_bytes
                        print(f"   [!] Erro ao processar chave {key}: {e}")
                        
    except Exception as e:
        print(f"\n[Error] Falha ao comunicar com o Cloudflare R2: {e}")
        sys.exit(1)
        
    print("\n" + "=" * 60)
    print("RESUMO DA EXECUÇÃO")
    print(f"Total de imagens encontradas: {images_processed}")
    print(f"Total de imagens redimensionadas: {images_resized}")
    print(f"Espaço original total: {total_original_bytes / (1024 * 1024):.2f} MB")
    print(f"Espaço otimizado estimado: {total_new_bytes / (1024 * 1024):.2f} MB")
    print(f"Economia de espaço total: {(total_original_bytes - total_new_bytes) / (1024 * 1024):.2f} MB")
    print("=" * 60)
    if DRY_RUN:
        print("DICA: Para aplicar as alterações de verdade no bucket, edite o arquivo e defina 'DRY_RUN = False'.")
    print("=" * 60)

if __name__ == "__main__":
    run_migration()
