import sys
import argparse
import re
from sqlalchemy import create_engine, text
from app.core.config import get_settings

def parse_args():
    parser = argparse.ArgumentParser(description="Migrar as URLs públicas do banco de dados do Backblaze B2 para o Cloudflare R2.")
    parser.add_argument("--old", help="URL base antiga do Backblaze B2 (ex: https://f005.backblazeb2.com/file/ump-gestao-bucket-key)")
    parser.add_argument("--new", help="URL base nova do Cloudflare R2 (ex: https://pub-xxxxxx.r2.dev)")
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Adicionar o diretório pai ao path caso executado diretamente
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    settings = get_settings()
    
    # 1. Determinar URL antiga
    old_base = args.old
    if not old_base:
        if settings.b2_endpoint_url and settings.b2_bucket_name:
            match = re.search(r'(\w+)-(\w+)-(\d+)', settings.b2_endpoint_url)
            region_num = match.group(3) if match else "005"
            old_base = f"https://f{region_num}.backblazeb2.com/file/{settings.b2_bucket_name}"
        else:
            print("Erro: URL base antiga não informada e não pôde ser calculada a partir das configurações do B2. Passe com --old")
            sys.exit(1)
            
    # 2. Determinar URL nova
    new_base = args.new
    if not new_base:
        if settings.r2_public_domain:
            new_base = settings.r2_public_domain.rstrip('/')
        else:
            print("Erro: URL base nova do R2 não informada e não encontrada no .env. Passe com --new")
            sys.exit(1)

    print(f"Iniciando migração de URLs do banco de dados:")
    print(f" -> De:   {old_base}")
    print(f" -> Para: {new_base}")
    print("-" * 50)

    # 3. Conectar ao banco
    db_url = settings.database_url
    if not db_url:
        print("Erro: DATABASE_URL não configurada nas variáveis de ambiente.")
        sys.exit(1)
        
    engine = create_engine(db_url)
    
    # Mapeamento de tabelas e colunas
    updates = [
        ("local_umps", "logo_url"),
        ("local_umps", "pix_qr_url"),
        ("federations", "logo_url"),
        ("member_monthly_fees", "receipt_url"),
        ("member_aci_contributions", "receipt_url"),
        ("membership_fees", "receipt_url"),
        ("report_signatures", "report_url"),
        ("financial_periods", "report_url"),
        ("financial_periods", "receipts_report_url"),
        ("financial_transactions", "receipt_url"),
        ("activity_reports", "report_url"),
        ("activity_photos", "photo_url"),
    ]
    
    with engine.begin() as conn:
        for table, col in updates:
            # Verifica se a tabela e a coluna existem
            table_check = conn.execute(text(f"""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = :table
                )
            """), {"table": table}).scalar()
            
            if not table_check:
                print(f"Tabela '{table}' não existe no banco de dados. Pulando...")
                continue
                
            col_check = conn.execute(text(f"""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = :table AND column_name = :col
                )
            """), {"table": table, "col": col}).scalar()
            
            if not col_check:
                print(f"Coluna '{col}' na tabela '{table}' não existe. Pulando...")
                continue

            # Conta linhas para atualizar
            check_query = text(f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE :old_base_like")
            count = conn.execute(check_query, {"old_base_like": f"{old_base}%"}).scalar()
            
            if count > 0:
                print(f"Tabela '{table}' (coluna '{col}'): {count} linha(s) encontrada(s). Atualizando...")
                update_query = text(f"""
                    UPDATE {table}
                    SET {col} = REPLACE({col}, :old_base, :new_base)
                    WHERE {col} LIKE :old_base_like
                """)
                conn.execute(update_query, {
                    "old_base": old_base,
                    "new_base": new_base,
                    "old_base_like": f"{old_base}%"
                })
            else:
                print(f"Tabela '{table}' (coluna '{col}'): Nenhuma linha encontrada.")
                
    print("-" * 50)
    print("Migração de URLs concluída com sucesso!")

if __name__ == "__main__":
    main()
