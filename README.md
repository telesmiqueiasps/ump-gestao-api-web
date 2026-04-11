# UMP Gestão POPB— Plataforma de Gestão da União de Mocidade Presbiteriana do Presbitério Oeste da Paraíba

Plataforma web completa para gestão de sociedades da União de Mocidade Presbiteriana (UMP), desenvolvida para o Presbitério Oeste da Paraíba (POPB). Suporta múltiplas organizações com hierarquia Federação → UMPs Locais, isolamento total de dados por organização e sistema de permissões por cargo.

---

## Stack e Infraestrutura

| Camada | Tecnologia | Serviço | URL |
|---|---|---|---|
| Backend | FastAPI (Python 3.11) | Render.com (Free) | https://ump-gestao-api.onrender.com |
| Frontend | HTML/CSS/JS puro (PWA) | Netlify | https://umpgestao.netlify.app |
| Banco | PostgreSQL | Supabase (Free) | Connection Pooler porta 6543 |
| Arquivos | S3-compatible | Backblaze B2 | bucket: `ump-gestao-bucket` |
| Repositório | Git | GitHub | https://github.com/telesmiqueiasps/ump-gestao-api-web |

### Estrutura do Repositório (Monorepo)

```
ump-gestao-api-web/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/          # config, security, dependencies
│   │   ├── db/            # session.py
│   │   ├── models/        # SQLAlchemy models
│   │   ├── routers/       # FastAPI routers
│   │   ├── services/      # storage.py, pdf_generator.py
│   │   └── assets/        # ipb_logo.png (para PDFs)
│   ├── requirements.txt
│   ├── render.yaml
│   ├── runtime.txt        # python-3.11.9
│   └── .python-version
└── frontend/
    ├── index.html         # Login
    ├── validar.html       # Validação pública de documentos
    ├── manifest.json
    ├── sw.js
    ├── _headers           # Cache-Control Netlify
    ├── _redirects
    ├── pages/             # Todas as páginas da aplicação
    └── assets/
        ├── css/           # main.css, components.css, layout.css
        ├── js/            # api.js, auth.js, router.v3.js, utils.js
        └── img/           # logos e ícones PWA
```

---

## Banco de Dados

### Tabelas Principais

| Tabela | Descrição |
|---|---|
| `federations` | Federações de mocidades |
| `local_umps` | UMPs Locais vinculadas a uma federação |
| `users` | Usuários do sistema |
| `user_roles` | Cargos dos usuários por organização |
| `financial_periods` | Períodos financeiros anuais |
| `financial_transactions` | Lançamentos financeiros |
| `members` | Sócios das UMPs Locais |
| `board_members` | Membros da diretoria |
| `activity_secretaries` | Secretários de atividades |
| `member_monthly_fees` | Mensalidades dos sócios |
| `member_aci_contributions` | Contribuições ACI dos sócios |
| `federation_notices` | Avisos da federação para locais |
| `report_signatures` | Assinaturas digitais de relatórios |
| `meetings` | Reuniões e atas |
| `meeting_attendees` | Presentes nas reuniões |

### Campos Importantes

**`financial_periods`**
- `is_closed` — período encerrado definitivamente (irreversível)
- `is_locked` — período bloqueado por assinatura digital (reversível)
- `ready_to_close` — marcado pelo tesoureiro como pronto
- `report_url` — URL do relatório financeiro no B2
- `receipts_report_url` — URL do relatório de comprovantes no B2
- `validation_code` — código de validação da assinatura digital
- `data_hash` — hash SHA-256 dos dados do período
- `observations` — observações do período (aparecem no PDF)

**`members`**
- `is_board_member` — indica se o sócio também é membro da diretoria (evita duplicação nas atas)

**`local_umps` / `federations`**
- `theme_color` — cor tema para relatórios PDF (#hex)
- `society_type` — tipo: UMP, UPH, SAF, UPA
- `logo_url` — URL da logo no Backblaze B2

### Enums PostgreSQL

```sql
board_role: presidente, vice_presidente, 1_secretario, 2_secretario,
            tesoureiro, secretario_executivo, secretario_presbiterial, conselheiro
org_type:   federation, local_ump
transaction_type: outras_receitas, outras_despesas, aci_recebida, aci_enviada
member_type: ativo, cooperador
```

> **Atenção:** SQLAlchemy usa `values_callable=lambda x: [e.value for e in x]` em todos os `SAEnum` para compatibilidade com valores que começam com número (`1_secretario`, `2_secretario`).

---

## Backend

### Dependências Principais

```
fastapi, uvicorn, sqlalchemy, psycopg2-binary
python-jose, passlib, bcrypt==4.0.1
boto3 (Backblaze B2 via S3)
reportlab==4.2.2, Pillow==10.4.0 (geração de PDFs)
qrcode[pil]==7.4.2 (QR codes nos PDFs assinados)
```

### Routers

| Prefixo | Arquivo | Descrição |
|---|---|---|
| `/api/auth` | auth.py | Login, refresh token, alteração de senha |
| `/api/federations` | federations.py | CRUD de federações, logo, UMPs locais |
| `/api/local-umps` | local_umps.py | CRUD de locais, logo, relatórios, inativação |
| `/api/users` | users.py | Gerenciamento de usuários |
| `/api/finances` | finances.py | Períodos, lançamentos, relatórios, encerramento |
| `/api/board` | board.py | Diretoria e secretários de atividades |
| `/api/members` | members.py | Sócios, aniversariantes |
| `/api/member-fees` | member_fees.py | Mensalidades e ACI dos sócios |
| `/api/notices` | notices.py | Avisos da federação para locais |
| `/api/signatures` | signatures.py | Validação pública de documentos |
| `/api/meetings` | meetings.py | Reuniões, atas, presentes, PDF |

### Autenticação

- JWT com access token (30min) + refresh token (7 dias)
- Claims incluem: `org_id`, `org_type`, `roles`
- Bcrypt fixado em 4.0.1 (compatibilidade com passlib 1.7.4)
- Usuários inativos (`is_active=False`) são bloqueados no login

### Armazenamento de Arquivos (Backblaze B2)

- Bucket privado — acesso via pre-signed URLs (1h para visualização)
- Para exibir imagens no browser sem CORS: backend baixa e retorna base64
- Exclusão de arquivos: usa `list_object_versions` + `delete_objects` (remove todas as versões/markers)
- Estrutura de pastas:
  - `logos/federations/{id}/`
  - `logos/local_umps/{id}/`
  - `receipts/{org_id}/{tx_id}/`
  - `receipts/members/{member_id}/monthly/{fee_id}/`
  - `receipts/members/{member_id}/aci/{contrib_id}/`
  - `reports/{org_id}/{year}/`
  - `signatures/{org_id}/{year}/`

### Geração de PDFs (reportlab)

O arquivo `backend/app/services/pdf_generator.py` contém:

- `generate_financial_report()` — relatório financeiro com logo, cor tema, tabelas por mês e bloco de assinatura digital
- `generate_receipts_report()` — relatório de comprovantes com imagens embutidas, logo e dados dos responsáveis
- `generate_meeting_report()` — ata/registro de atos no modelo oficial IPB

Todos suportam `theme_color` dinâmico (hex → RGB) e logo da organização via bytes.

---

## Frontend

### Arquitetura

- HTML/CSS/JS puro — sem framework
- Módulos ES (`type="module"`) em todas as páginas
- PWA com manifest, service worker e bottom navigation mobile
- Roteamento simples por navegação entre páginas HTML

### Arquivos JS Principais

| Arquivo | Função |
|---|---|
| `api.js` | Fetch com auth, timeout 30s, refresh automático |
| `auth.js` | Login, logout, getUser, verificação de org/cargo |
| `router.v3.js` | renderShell (async), buildNavHTML, canAccessPage, renderBottomNav, initMobileMenu |
| `utils.js` | formatCurrency, formatDate, openModal, closeModal, showAlert, avatarHtml, nameToColor, getSocietyLabel |

### Páginas

| Página | Acesso |
|---|---|
| `index.html` | Login com retry automático (cold start Render) |
| `validar.html` | Público — validação de documentos assinados |
| `dashboard.html` | Todos os cargos |
| `profile.html` | Todos os cargos |
| `finances.html` | Presidente, Vice, Tesoureiro, Conselheiro, Sec. Presbiterial |
| `members.html` | Apenas local — Presidente, Vice, Tesoureiro, Conselheiro, Sec. Presbiterial |
| `board.html` | Presidente, Vice, Conselheiro, Sec. Presbiterial |
| `local-umps.html` | Apenas federação — Presidente, Vice, Conselheiro, Sec. Presbiterial |
| `secretary.html` | Presidente, Vice, 1º Sec, 2º Sec, Sec. Executivo, Conselheiro, Sec. Presbiterial |
| `president.html` | Presidente, Vice, Conselheiro, Sec. Presbiterial |
| `notices.html` | Todos os cargos |

---

## Sistema de Permissões por Cargo

### Hierarquia

```
Federação
└── UMPs Locais (criadas e gerenciadas pela federação)
```

### Cargos e Acessos

| Cargo | Dashboard | Financeiro | Sócios | Diretoria | Locais | Secretaria | Presidência | Avisos |
|---|---|---|---|---|---|---|---|---|
| Presidente | ✓ | ✓ | ✓ | ✓ | ✓ (fed) | ✓ | ✓ | ✓ |
| Vice-Presidente | ✓ | ✓ | ✓ | ✓ | ✓ (fed) | ✓ | ✓ | ✓ |
| Tesoureiro | ✓ | ✓ | ✓ | — | — | — | — | ✓ |
| 1º / 2º Secretário | ✓ | — | ✓ | — | — | ✓ | — | ✓ |
| Sec. Executivo | ✓ | — | ✓ | — | — | ✓ | — | ✓ |
| Sec. Presbiterial | ✓ | ✓ | ✓ | ✓ | ✓ (fed) | ✓ | ✓ | ✓ |
| Conselheiro | ✓ | ✓ | ✓ | ✓ | ✓ (fed) | ✓ | ✓ | ✓ |

---

## Funcionalidades Implementadas

### Autenticação e Perfil
- Login com retry automático (servidor Render pode estar dormindo)
- Refresh token automático
- Alteração de senha via modal na sidebar
- Perfil com logo (B2), cor tema, tipo de sociedade (UMP/UPH/SAF/UPA)
- Nomenclatura dinâmica em todo o sistema conforme tipo de sociedade

### Financeiro
- Períodos anuais com saldo inicial
- Tela de seleção de meses em grid (cards com saldo, indicador visual)
- Tela de detalhe do mês com navegação ← →
- Lançamentos: outras_receitas, outras_despesas, aci_recebida, aci_enviada
- Comprovantes no B2 com pre-signed URLs
- Ícone 👁️ inline para comprovante no mobile
- Observações do período (aparecem no PDF)
- **Encerramento definitivo** (irreversível):
  - Gera relatório financeiro PDF com assinatura digital
  - Gera relatório de comprovantes PDF com imagens embutidas
  - Salva ambos no B2 e vincula ao período
  - Gera QR Code + código de validação + hash SHA-256
- **Marcação de pronto** (tesoureiro/vice) → notificação na aba Presidência
- **Encerramento** (apenas presidente/vice/sec.presbiterial/conselheiro)
- Rotina de limpeza de comprovantes por ano
- Botão "Ver Relatórios" com links para os PDFs finais

### Assinatura Digital
- Código de validação único (48 chars, URL-safe)
- Hash SHA-256 dos dados financeiros
- QR Code no PDF apontando para `umpgestao.netlify.app/validar.html?codigo=XXX`
- Página pública de validação sem autenticação
- Histórico de assinaturas na aba Presidência
- Invalidação automática ao desbloquear período

### Sócios (apenas UMP Local)
- CRUD completo: nome, tipo (ativo/cooperador), email, telefone, nascimento, ingresso
- Campo `is_board_member` para evitar duplicação nas atas
- **Mensalidades**: grid de 12 meses, verde=pago/cinza=pendente
  - Ao pagar: cria lançamento `outras_receitas` no financeiro
  - Ao excluir: remove lançamento e comprovante do B2
- **ACI**: contribuições parceladas criam lançamento `aci_recebida`
  - Barra de progresso por sócio
  - Valor anual configurável (2% do salário mínimo)
  - Ao excluir: remove lançamento do financeiro
- Comprovantes de mensalidade e ACI sincronizados com o financeiro

### Dashboard
- Cards financeiros: saldo inicial, entradas, saídas, saldo final, ACI recebida, ACI enviada
- Card ACI (apenas local): total a repassar, arrecadado, falta, barra de progresso
- Avisos rápidos do mês

### Diretoria
- CRUD com todos os cargos por tipo de organização
- Campo de contato com máscara de telefone
- Avatares de iniciais coloridos (determinísticos por nome)
- **Secretários de atividades**: nome, secretaria, contato (cadastro separado)
- Seção de usuários do sistema para presidente/vice da federação

### UMPs Locais (apenas federação)
- CRUD simplificado (nome, igreja, presbitério — demais dados preenchidos pela própria local)
- Gestão de usuários por local
- **Inativação**: bloqueia todos os usuários da local
- **Reativação**: restaura acesso dos usuários
- Datas de inativação e reativação
- Filtros: Ativas / Inativas / Todas + busca por nome
- **Relatórios das locais**: federação acessa relatórios financeiros de cada local
  - Modal com abas: Financeiro / Atividades / Estatísticas (estas em breve)

### Avisos
- **Federação**: envia avisos para todas as locais ou local específica, com expiração opcional
- **Local**: recebe avisos da federação, vê aniversariantes dos sócios do mês, aniversário da própria sociedade
- **Federação**: vê aniversários das locais no mês
- Badge na sidebar com contador de notificações do dia

### Secretaria (Módulo de Atas)
- Tipos de reunião: Plenária, Ordinária, Congresso, Comissão Executiva, Assembleia, etc.
- Status: Rascunho / Publicado (publicado bloqueia edição)
- Numeração manual do registro (ex: 001-2026)
- **Identificação**: número, tipo, título, data/hora início e término, local, cidade/UF, endereço, presidente e secretário da reunião (seletor da diretoria)
- **Presentes**:
  - Carregamento automático de diretoria, secretários de atividades e sócios
  - Categorias: Diretoria, Conselheiro(a)/Sec. Presbiterial, Sec. Atividades, Delegados (por local), Sócios, Visitantes
  - Marcação de presente/ausente com contagem automática
  - Delegados vinculados a locais cadastradas (select para federação)
  - Visitantes com observação
- **Seções de texto** com auto-save (1,5s): Ato Devocional, Pauta, Resoluções, Observações, Encerramento
- Botões de inserção rápida de tópicos (• Sub-tópico, - Numerado)
- Geração de PDF no modelo oficial IPB com logos, tabelas e assinatura do secretário

### Presidência
- Aba Financeiro: lista períodos marcados como prontos para encerramento
- Encerramento com um clique (gera PDFs assinados automaticamente)
- Histórico de relatórios com botão "Ver PDF"
- Aba Outros: em desenvolvimento

### PWA
- Manifest completo com shortcuts, display standalone, orientação portrait
- Service Worker v8: cacheia apenas imagens, nunca JS/CSS/HTML
- Bottom navigation mobile com ícones PNG para Dashboard, Financeiro e Diretoria
- Sidebar como drawer no mobile com overlay
- Modais como bottom sheet no mobile (acima da bottom nav)
- Responsividade completa com `viewport-fit=cover` para iPhone com notch

---

## Tipo de Sociedade

O sistema suporta diferentes tipos de sociedade com nomenclatura dinâmica:

| Sigla | Nome | Membro | Presidente | Tesoureiro |
|---|---|---|---|---|
| UMP | União de Mocidade Presbiteriana | Sócio | Presidente | Tesoureiro(a) |
| UPH | União Presbiteriana de Homens | Membro | Presidente | Tesoureiro |
| SAF | Sociedade Auxiliadora Feminina | Associada | Presidente | Tesoureira |
| UPA | União Presbiteriana de Adolescentes | Participante | Presidente | Tesoureiro(a) |

A nomenclatura é aplicada em: sidebar, títulos de páginas, botões, relatórios PDF e atas.

---

## Geração de Relatórios PDF

### Relatório Financeiro
- Cabeçalho com logo da organização + bloco azul com nome e ano
- Cor tema dinâmica (configurada no perfil)
- Tabela de identificação da organização
- Tabela financeira: saldo inicial, ACI, outras receitas/despesas, totais, saldo final
- Campo de observações
- Assinaturas (Presidente e Tesoureiro)
- **Com assinatura digital** (encerramento definitivo):
  - QR Code + código de validação + hash SHA-256
  - Nome e cargo dos signatários
  - Link para validação pública
- Páginas dos meses: cabeçalho com logo, mini resumo, tabela de lançamentos com numeração

### Relatório de Comprovantes
- Capa elaborada com logo, dados do período, responsáveis
- Uma seção por lançamento com comprovante: dados + imagem embutida
- Numeração coincide exatamente com o relatório financeiro
- PDFs externos: nota informativa (não embutidos)

### Registro de Atos (Ata)
- Layout no modelo oficial IPB com logos (IPB + organização)
- Tabela de identificação: número, datas, local, endereço, presidente
- Seção PRESENTES com quantitativos por categoria e listagem completa
- Delegados agrupados por local (federação)
- Seções de texto: Ato Devocional, Pauta, Resoluções, Observações, Encerramento
- Assinatura do secretário com cargo

---

## Validação Pública de Documentos

Qualquer pessoa pode validar a autenticidade de um relatório financeiro em:

```
https://umpgestao.netlify.app/validar.html?codigo=CODIGO_AQUI
```

Retorna:
- ✅ **Válido**: organização, ano fiscal, data de aprovação, aprovador, hash
- ⚠️ **Invalidado**: motivo e data da invalidação
- ❌ **Inválido**: código não encontrado ou não aprovado

Endpoint público (sem autenticação):
```
GET /api/finances/validate/{code}
```

---

## Configuração e Deploy

### Variáveis de Ambiente (Render)

```env
DATABASE_URL=postgresql://...@aws-0-sa-east-1.pooler.supabase.com:6543/postgres
SECRET_KEY=chave-secreta
B2_KEY_ID=key-id
B2_APPLICATION_KEY=application-key
B2_BUCKET_NAME=ump-gestao-bucket
B2_ENDPOINT_URL=https://s3.us-east-005.backblazeb2.com
PYTHON_VERSION=3.11.9
```

### Configuração do Supabase

Usar o **Transaction Pooler** (porta 6543) — o Render Free não suporta IPv6 (porta 5432).

### Deploy

- **Backend**: push para GitHub → Render detecta e deploya automaticamente
- **Frontend**: push para GitHub → Netlify deploya automaticamente
- **Cache bust**: renomear arquivos JS (ex: `router.v3.js`) força limpeza de cache

### SQL de Setup (rodar no Supabase)

```sql
-- Campos adicionados progressivamente ao longo do desenvolvimento
ALTER TABLE federations ADD COLUMN IF NOT EXISTS synodal_name VARCHAR(200);
ALTER TABLE federations ADD COLUMN IF NOT EXISTS theme_color VARCHAR(7) DEFAULT '#1a2a6c';
ALTER TABLE federations ADD COLUMN IF NOT EXISTS society_type VARCHAR(10) DEFAULT 'UMP';

ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS pastor_contact VARCHAR(100);
ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS organization_date DATE;
ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS monthly_fee_value NUMERIC(10,2) DEFAULT 0;
ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS aci_year_value NUMERIC(10,2) DEFAULT 0;
ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS theme_color VARCHAR(7) DEFAULT '#1a2a6c';
ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS society_type VARCHAR(10) DEFAULT 'UMP';
ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;
ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS reactivated_at TIMESTAMPTZ;

ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS report_url TEXT;
ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS receipts_report_url TEXT;
ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS is_locked BOOLEAN DEFAULT FALSE;
ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS signature_id UUID;
ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS ready_to_close BOOLEAN DEFAULT FALSE;
ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS ready_at TIMESTAMPTZ;
ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS ready_by UUID REFERENCES users(id);
ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS validation_code VARCHAR(64);
ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS data_hash TEXT;
ALTER TABLE financial_periods ADD COLUMN IF NOT EXISTS observations TEXT;

ALTER TABLE board_members ADD COLUMN IF NOT EXISTS contact VARCHAR(20);

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;

ALTER TABLE members ADD COLUMN IF NOT EXISTS is_board_member BOOLEAN DEFAULT FALSE;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_secretary VARCHAR(200);
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_secretary_role VARCHAR(100);
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_president_role VARCHAR(100);

-- Tabelas criadas do zero
CREATE TABLE IF NOT EXISTS member_monthly_fees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id),
    local_ump_id UUID NOT NULL REFERENCES local_umps(id),
    reference_month DATE NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    paid_at DATE,
    is_paid BOOLEAN DEFAULT FALSE,
    receipt_url TEXT,
    transaction_id UUID REFERENCES financial_transactions(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(member_id, reference_month)
);

CREATE TABLE IF NOT EXISTS member_aci_contributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id),
    local_ump_id UUID NOT NULL REFERENCES local_umps(id),
    fiscal_year INTEGER NOT NULL,
    payment_date DATE NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    receipt_url TEXT,
    transaction_id UUID REFERENCES financial_transactions(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS federation_notices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    federation_id UUID NOT NULL REFERENCES federations(id),
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    target_type VARCHAR(10) NOT NULL DEFAULT 'all',
    target_local_id UUID REFERENCES local_umps(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS report_signatures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    fiscal_year INTEGER NOT NULL,
    period_id UUID REFERENCES financial_periods(id),
    requested_by UUID NOT NULL REFERENCES users(id),
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,
    validation_code VARCHAR(64) NOT NULL UNIQUE,
    report_url TEXT,
    data_hash TEXT NOT NULL,
    snapshot_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    invalidated_at TIMESTAMPTZ,
    invalidated_reason TEXT
);

CREATE TABLE IF NOT EXISTS activity_secretaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    organization_type VARCHAR(20) NOT NULL,
    member_name VARCHAR(200) NOT NULL,
    activity_name VARCHAR(200) NOT NULL,
    contact VARCHAR(20),
    fiscal_year INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    organization_type VARCHAR(20) NOT NULL,
    record_number VARCHAR(20) NOT NULL,
    meeting_type VARCHAR(50) NOT NULL,
    title VARCHAR(200),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    location_name VARCHAR(200),
    city VARCHAR(100),
    state VARCHAR(2) DEFAULT 'PB',
    address TEXT,
    meeting_president VARCHAR(200),
    meeting_president_role VARCHAR(100),
    meeting_secretary VARCHAR(200),
    meeting_secretary_role VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    section_devotional TEXT,
    section_agenda TEXT,
    section_resolutions TEXT,
    section_observations TEXT,
    section_closing TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meeting_attendees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    attendee_type VARCHAR(30) NOT NULL,
    name VARCHAR(200) NOT NULL,
    local_name VARCHAR(200),
    observation VARCHAR(300),
    is_present BOOLEAN DEFAULT TRUE,
    source_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Notas Técnicas Importantes

### SQLAlchemy + Enums PostgreSQL
O enum `board_role` tem valores que começam com número (`1_secretario`, `2_secretario`). Isso exige `values_callable` em todas as colunas:
```python
Column(SAEnum(BoardRole, name="board_role",
              values_callable=lambda x: [e.value for e in x]))
```

### CORS e Backblaze B2
Imagens do B2 não podem ser carregadas via `fetch` no browser (bloqueio CORS). Solução: backend baixa via boto3 e retorna como base64:
```python
response = client.get_object(Bucket=bucket, Key=key)
b64 = base64.b64encode(response['Body'].read()).decode('utf-8')
return {"base64": f"data:{content_type};base64,{b64}"}
```

### Fuso Horário nas Atas
Datas das reuniões são salvas sem timezone (naive datetime) para evitar conversão automática de UTC±3:
```python
dt = dateutil.parser.parse(dt_str)
return dt.replace(tzinfo=None)
```

### Service Worker
Cache apenas de imagens — nunca JS, CSS ou HTML:
```javascript
// sw.js versão v8
// Nunca intercepta: .html, .js, .css, /api/, backblazeb2.com
// Cacheia apenas: .png, .jpg, .webp, .ico, .svg
```

### Cold Start (Render Free)
O servidor dorme após 15min sem uso. O login tem retry automático (5 tentativas, delays progressivos) com mensagem ao usuário.

---

## Estimativa de Custos (Cenário Atual)

| Serviço | Plano | Custo | Limite |
|---|---|---|---|
| Render | Free | $0 | Cold start após 15min, 1 instância |
| Supabase | Free | $0 | 500MB banco, pausa após 1 sem sem uso |
| Backblaze B2 | Free tier | $0 | Primeiros 10GB grátis permanentemente |
| Netlify | Free | $0 | 100GB bandwidth/mês |

Com 20 organizações, 6 usuários cada, 1 lançamento/dia e 10 acessos simultâneos no pico, o sistema está muito confortável no free tier por anos.

---

## Desenvolvido por

Miquéias Teles Pereira da Silva   
2026