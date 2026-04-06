import io
import re
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Image, Paragraph
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


# ── Cores ──────────────────────────────────────────────────────
BLUE      = colors.HexColor('#1a2a6c')
WHITE     = colors.white
GRAY_ROW  = colors.HexColor('#f5f7fa')
GRAY_LINE = colors.HexColor('#e2e8f0')
GRAY_TXT  = colors.HexColor('#64748b')
BLACK     = colors.HexColor('#1e293b')
GREEN     = colors.HexColor('#16a34a')
RED_C     = colors.HexColor('#dc2626')
YELLOW_BG = colors.HexColor('#fffde7')


def _theme(hex_color):
    try:
        return colors.HexColor(hex_color)
    except:
        return BLUE


def _fc(v):
    try:
        n = float(v)
        s = f'{abs(n):,.2f}'.replace(',','X').replace('.', ',').replace('X','.')
        return f'R$ {s}'
    except:
        return 'R$ 0,00'


def _fd(d):
    if not d:
        return '—'
    try:
        s = str(d).split('T')[0]
        y, mo, day = s.split('-')
        return f'{day}/{mo}/{y}'
    except:
        return str(d)


MONTHS = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
          'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']


def _logo_image(logo_bytes, w_mm, h_mm):
    if not logo_bytes:
        return None
    try:
        buf = io.BytesIO(logo_bytes)
        img = Image(buf, width=w_mm*mm, height=h_mm*mm)
        return img
    except:
        return None


def _download_b2(client, bucket, url):
    try:
        match = re.search(rf'/file/{re.escape(bucket)}/(.+)$', url)
        if not match:
            match = re.search(rf'/{re.escape(bucket)}/(.+)$', url)
        if not match:
            return None, None
        key = match.group(1)
        resp = client.get_object(Bucket=bucket, Key=key)
        ct = resp.get('ContentType', 'image/png')
        return resp['Body'].read(), ct
    except:
        return None, None


# ═══════════════════════════════════════════════════════════════
# RELATÓRIO FINANCEIRO
# ═══════════════════════════════════════════════════════════════

def generate_financial_report(
    org_data, period_data, months_data, board_data,
    logo_bytes=None, logo_content_type=None, theme_color='#1a2a6c',
):
    buf = io.BytesIO()
    W_PAGE, H_PAGE = A4
    ML = MR = 14*mm
    MT = MB = 14*mm
    W = W_PAGE - ML - MR

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB)

    TC = _theme(theme_color)
    year = period_data.get('fiscal_year')
    org_name = (org_data.get('name') or '').upper()
    is_fed = org_data.get('organization_type') == 'federation'
    story = []

    # ── Estilos base ──
    def ps(size=8, color=BLACK, bold=False, align=TA_LEFT, leading=None):
        return ParagraphStyle('_',
            fontSize=size,
            textColor=color,
            fontName='Helvetica-Bold' if bold else 'Helvetica',
            alignment=align,
            leading=leading or size * 1.3,
            spaceAfter=0, spaceBefore=0,
        )

    # ════════════
    # CAPA
    # ════════════

    # ── Cabeçalho: logo + bloco azul ──
    LOGO_W = 28
    HDR_H  = 35*mm

    logo_img = _logo_image(logo_bytes, LOGO_W, LOGO_W)
    title_w  = W - (LOGO_W*mm if logo_img else 0)

    # Bloco azul de título
    title_cell = Table([[
        Paragraph('RELATÓRIO FINANCEIRO DA', ps(9, WHITE, align=TA_CENTER)),
        Paragraph(org_name, ps(13, WHITE, bold=True, align=TA_CENTER)),
        Paragraph(f'Ano {year}', ps(8, WHITE, align=TA_CENTER)),
    ]], colWidths=[title_w])
    title_cell.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), TC),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('LEFTPADDING',   (0,0), (-1,-1), 6),
        ('RIGHTPADDING',  (0,0), (-1,-1), 6),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    # Precisa de altura fixa — usa Table externa para forçar
    # Logo à esquerda, título à direita
    if logo_img:
        hdr_data = [[logo_img, title_cell]]
        hdr_cw   = [LOGO_W*mm, title_w]
    else:
        hdr_data = [[title_cell]]
        hdr_cw   = [W]

    hdr_outer = Table(hdr_data, colWidths=hdr_cw, rowHeights=[HDR_H])
    hdr_outer.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        # Fundo azul em toda a célula do título
        ('BACKGROUND',    (1 if logo_img else 0, 0), (-1,-1), TC),
    ]))
    story.append(hdr_outer)
    story.append(Spacer(1, 6*mm))

    # ── Faixa INFORMAÇÕES GERAIS ──
    def section_bar(txt):
        t = Table([[Paragraph(txt, ps(9, WHITE, bold=True, align=TA_CENTER))]],
                  colWidths=[W], rowHeights=[7*mm])
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(-1,-1), TC),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('TOPPADDING',    (0,0),(-1,-1), 0),
            ('BOTTOMPADDING', (0,0),(-1,-1), 0),
        ]))
        return t

    story.append(section_bar('INFORMAÇÕES GERAIS'))
    story.append(Spacer(1, 1*mm))
    story.append(section_bar('IDENTIFICAÇÃO DA ORGANIZAÇÃO'))

    # ── Tabela de identificação ──
    LW = 45*mm   # largura da coluna de rótulo
    VW = W - LW  # largura da coluna de valor

    def id_row(label, value, shade=False):
        bg = GRAY_ROW if shade else WHITE
        return ([
            Paragraph(label.upper(), ps(7, GRAY_TXT, align=TA_RIGHT)),
            Paragraph(str(value or '—'), ps(7.5, BLACK)),
        ], bg)

    def id_row2(l1, v1, l2, v2, shade=False):
        bg = GRAY_ROW if shade else WHITE
        hw = W / 2
        hlw = 45*mm
        hvw = hw - hlw
        return ([
            Paragraph(l1.upper(), ps(7, GRAY_TXT, align=TA_RIGHT)),
            Paragraph(str(v1 or '—'), ps(7.5, BLACK)),
            Paragraph(l2.upper(), ps(7, GRAY_TXT, align=TA_RIGHT)),
            Paragraph(str(v2 or '—'), ps(7.5, BLACK)),
        ], bg, True)  # True = 4 colunas

    org_label = 'FEDERAÇÃO' if is_fed else (org_data.get('society_type') or 'UMP')
    presidente = next((b for b in board_data if b.get('role') == 'presidente'), None)
    tesoureiro  = next((b for b in board_data if b.get('role') == 'tesoureiro'), None)

    id_rows_def = [
        id_row(org_label,  (org_data.get('name') or '').upper()),
        id_row('PRESBITÉRIO', (org_data.get('presbytery_name') or '').upper(), True),
    ]
    if not is_fed:
        id_rows_def.append(id_row('IGREJA', (org_data.get('church_name') or '').upper()))
        id_rows_def.append(id_row('PASTOR', (org_data.get('pastor_name') or '—').upper(), True))

    id_rows_def.append(id_row2(
        'ANO VIGENTE', year,
        'DATA DO RELATÓRIO', datetime.date.today().strftime('%d/%m/%Y'),
        shade=len(id_rows_def) % 2 == 0
    ))
    id_rows_def.append(id_row('PRESIDENTE',
        (presidente.get('member_name') or '—').upper() if presidente else '—',
        shade=len(id_rows_def) % 2 == 1))
    id_rows_def.append(id_row('TESOUREIRO(A) RESPONSÁVEL',
        (tesoureiro.get('member_name') or '—').upper() if tesoureiro else '—',
        shade=len(id_rows_def) % 2 == 0))

    # Monta tabela de identificação
    id_data = []
    id_styles = [
        ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
    ]
    for ri, row_def in enumerate(id_rows_def):
        row_data, bg, *flags = row_def if len(row_def) == 3 else (*row_def, False)
        is_4col = flags[0] if flags else False
        id_data.append(row_data)
        if bg != WHITE:
            id_styles.append(('BACKGROUND', (0,ri),(-1,ri), bg))

    # Widths: linhas normais 2 col, linha de 4col divide ao meio
    id_table = Table(id_data, colWidths=[LW, VW])
    id_table.setStyle(TableStyle(id_styles))
    story.append(id_table)
    story.append(Spacer(1, 5*mm))

    # ── Tabela financeira ──
    total_in  = sum(float(m.get('total_in',  0)) for m in months_data)
    total_out = sum(float(m.get('total_out', 0)) for m in months_data)
    aci_in    = sum(
        sum(float(t['amount']) for t in m.get('transactions',[]) if t['transaction_type']=='aci_recebida')
        for m in months_data)
    aci_out   = sum(
        sum(float(t['amount']) for t in m.get('transactions',[]) if t['transaction_type']=='aci_enviada')
        for m in months_data)
    outras_rec = total_in  - aci_in
    outras_des = total_out - aci_out
    initial    = float(period_data.get('initial_balance', 0))
    final_bal  = float(period_data.get('final_balance', initial + total_in - total_out))

    story.append(section_bar(f'INFORMAÇÕES FINANCEIRAS {year}'))

    HW  = W / 2          # meia largura
    LLW = 38*mm          # rótulo dentro da meia
    RRW = HW - LLW       # valor dentro da meia

    def fin_cell(txt, bold=False, align=TA_LEFT, color=BLACK):
        return Paragraph(txt, ps(7.5, color, bold=bold, align=align))

    def fin_hdr(txt):
        return Paragraph(txt, ps(8, WHITE, bold=True, align=TA_CENTER))

    fin_data = [
        # Linha 0: saldo anterior — span completo
        [fin_cell(f'SALDO DO ANO ANTERIOR {year-1}', bold=True),
         fin_cell(_fc(initial), bold=True, align=TA_RIGHT),
         fin_cell('', bold=True), fin_cell('', bold=True)],

        # Linha 1: cabeçalhos RECEITAS / DESPESAS
        [fin_hdr(f'RECEITAS ({year})'), fin_hdr(''),
         fin_hdr(f'DESPESAS ({year})'), fin_hdr('')],

        # Linha 2
        [fin_cell('ACI Recebida'), fin_cell(_fc(aci_in), align=TA_RIGHT),
         fin_cell('ACI Enviada'), fin_cell(_fc(aci_out), align=TA_RIGHT)],

        # Linha 3
        [fin_cell('Outras Receitas (+)'), fin_cell(_fc(outras_rec), align=TA_RIGHT),
         fin_cell('Outras Despesas (−)'), fin_cell(_fc(outras_des), align=TA_RIGHT)],

        # Linha 4: totais
        [fin_cell('TOTAL DA RECEITA ANUAL', bold=True),
         fin_cell(_fc(total_in), bold=True, align=TA_RIGHT),
         fin_cell('TOTAL DA DESPESA ANUAL', bold=True),
         fin_cell(_fc(total_out), bold=True, align=TA_RIGHT)],

        # Linha 5: total geral / saldo final
        [fin_cell('TOTAL GERAL (SALDO + RECEITAS)', bold=True),
         fin_cell(_fc(initial + total_in), bold=True, align=TA_RIGHT),
         fin_cell(f'SALDO FINAL PARA {year+1}', bold=True),
         fin_cell(_fc(final_bal), bold=True, align=TA_RIGHT)],
    ]

    fin_table = Table(fin_data, colWidths=[LLW, RRW, LLW, RRW])
    fin_style = [
        ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 4),
        ('BOTTOMPADDING', (0,0),(-1,-1), 4),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
        # Linha 0: fundo azul span 0-1
        ('BACKGROUND',    (0,0),(1,0), TC),
        ('SPAN',          (0,0),(1,0)),
        # Linha 0: célula direita vazia com fundo branco
        ('BACKGROUND',    (2,0),(3,0), GRAY_ROW),
        ('SPAN',          (2,0),(3,0)),
        # Linha 1: cabeçalhos azuis
        ('BACKGROUND',    (0,1),(1,1), TC),
        ('BACKGROUND',    (2,1),(3,1), TC),
        ('SPAN',          (0,1),(1,1)),
        ('SPAN',          (2,1),(3,1)),
        # Linhas alternadas
        ('BACKGROUND',    (0,2),(-1,2), GRAY_ROW),
        ('BACKGROUND',    (0,4),(-1,4), GRAY_ROW),
        ('BACKGROUND',    (0,5),(-1,5), GRAY_ROW),
    ]
    fin_table.setStyle(TableStyle(fin_style))
    story.append(fin_table)
    story.append(Spacer(1, 3*mm))

    # ── Observações ──
    obs_data = [[
        Paragraph('OBSERVAÇÕES:', ps(7, GRAY_TXT, bold=True)),
        Paragraph('OBSERVAÇÕES:', ps(7, GRAY_TXT, bold=True)),
    ]]
    obs_t = Table(obs_data, colWidths=[HW-1*mm, HW-1*mm], rowHeights=[22*mm])
    obs_t.setStyle(TableStyle([
        ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
        ('BACKGROUND',    (0,0),(-1,-1), YELLOW_BG),
        ('VALIGN',        (0,0),(-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0),(-1,-1), 4),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
    ]))
    story.append(obs_t)
    story.append(Spacer(1, 3*mm))

    # ── Link dos comprovantes ──
    link_t = Table([[Paragraph('LINK DOS COMPROVANTES:', ps(7, GRAY_TXT, bold=True))]],
                   colWidths=[W], rowHeights=[8*mm])
    link_t.setStyle(TableStyle([
        ('GRID',       (0,0),(-1,-1), 0.5, GRAY_LINE),
        ('BACKGROUND', (0,0),(-1,-1), YELLOW_BG),
        ('VALIGN',     (0,0),(-1,-1), 'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1), 4),
    ]))
    story.append(link_t)
    story.append(Spacer(1, 8*mm))

    # ── Assinaturas ──
    SIG_W = (W - 20*mm) / 2
    pres_name = (presidente.get('member_name') or '').upper() if presidente else ''
    tes_name  = (tesoureiro.get('member_name')  or '').upper() if tesoureiro else ''

    def sig_block(name, role_label):
        return Table([
            [HRFlowable(width=SIG_W, thickness=1, color=BLACK)],
            [Paragraph(name,       ps(9, BLACK, bold=True, align=TA_CENTER))],
            [Paragraph(role_label, ps(8, BLACK,             align=TA_CENTER))],
            [Paragraph(org_name,   ps(8, BLACK, bold=True,  align=TA_CENTER))],
        ], colWidths=[SIG_W])

    sig_t = Table([[
        sig_block(pres_name, 'Presidente da'),
        Spacer(20*mm, 1),
        sig_block(tes_name,  'Tesoureiro(a) da'),
    ]], colWidths=[SIG_W, 20*mm, SIG_W])
    sig_t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(sig_t)
    story.append(Spacer(1, 6*mm))

    # ── Rodapé azul ──
    presby = (org_data.get('presbytery_name') or '').upper()
    footer_txt = f'{org_name} — {presby}' if presby else org_name
    ft = Table([[Paragraph(footer_txt, ps(7.5, WHITE, bold=True, align=TA_CENTER))]],
               colWidths=[W], rowHeights=[7*mm])
    ft.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,-1), TC),
        ('VALIGN',     (0,0),(-1,-1), 'MIDDLE'),
    ]))
    story.append(ft)

    # ════════════════════
    # PÁGINAS DOS MESES
    # ════════════════════
    TYPE_LABELS = {
        'outras_receitas': 'Outras Receitas',
        'outras_despesas': 'Outras Despesas',
        'aci_recebida':    'ACI Recebida',
        'aci_enviada':     'ACI Enviada',
    }
    INCOME = {'outras_receitas', 'aci_recebida'}

    # Numeração global dos lançamentos (igual ao relatório de comprovantes)
    global_tx_num = {}
    counter = 0
    for month in months_data:
        for t in month.get('transactions', []):
            counter += 1
            global_tx_num[t['id']] = counter

    for month in months_data:
        story.append(PageBreak())

        # Cabeçalho do mês — mesmo layout da capa
        month_title = month['month_label'].upper()
        if logo_img:
            m_logo = _logo_image(logo_bytes, 22, 22)
            mhdr_data = [[m_logo, Table([[
                Paragraph(org_name, ps(7, WHITE, align=TA_CENTER)),
                Paragraph(f'{month_title} {year}', ps(12, WHITE, bold=True, align=TA_CENTER)),
                Paragraph('Relatório Financeiro Mensal', ps(6.5, WHITE, align=TA_CENTER)),
            ]], colWidths=[W - 22*mm])]]
            mhdr_cw = [22*mm, W - 22*mm]
        else:
            mhdr_data = [[Table([[
                Paragraph(org_name, ps(7, WHITE, align=TA_CENTER)),
                Paragraph(f'{month_title} {year}', ps(12, WHITE, bold=True, align=TA_CENTER)),
                Paragraph('Relatório Financeiro Mensal', ps(6.5, WHITE, align=TA_CENTER)),
            ]], colWidths=[W])]]
            mhdr_cw = [W]

        mhdr = Table(mhdr_data, colWidths=mhdr_cw, rowHeights=[28*mm])
        mhdr_style = [
            ('VALIGN',        (0,0),(-1,-1),'MIDDLE'),
            ('LEFTPADDING',   (0,0),(-1,-1),0),
            ('RIGHTPADDING',  (0,0),(-1,-1),0),
            ('TOPPADDING',    (0,0),(-1,-1),0),
            ('BOTTOMPADDING', (0,0),(-1,-1),0),
        ]
        if logo_img:
            mhdr_style.append(('BACKGROUND', (1,0),(1,0), TC))
        else:
            mhdr_style.append(('BACKGROUND', (0,0),(0,0), TC))
        mhdr.setStyle(TableStyle(mhdr_style))
        story.append(mhdr)
        story.append(Spacer(1, 4*mm))

        # Mini resumo do mês
        QW = W / 4
        summary_rows = [[
            Table([[
                Paragraph('SALDO ANTERIOR', ps(6.5, GRAY_TXT, align=TA_CENTER)),
                Paragraph(_fc(month['opening_balance']), ps(8.5, TC, bold=True, align=TA_CENTER)),
            ]], colWidths=[QW]),
            Table([[
                Paragraph('ENTRADAS', ps(6.5, GRAY_TXT, align=TA_CENTER)),
                Paragraph(_fc(month['total_in']), ps(8.5, GREEN, bold=True, align=TA_CENTER)),
            ]], colWidths=[QW]),
            Table([[
                Paragraph('SAÍDAS', ps(6.5, GRAY_TXT, align=TA_CENTER)),
                Paragraph(_fc(month['total_out']), ps(8.5, RED_C, bold=True, align=TA_CENTER)),
            ]], colWidths=[QW]),
            Table([[
                Paragraph('SALDO DO MÊS', ps(6.5, GRAY_TXT, align=TA_CENTER)),
                Paragraph(_fc(month['closing_balance']), ps(8.5, TC, bold=True, align=TA_CENTER)),
            ]], colWidths=[QW]),
        ]]
        sum_t = Table(summary_rows, colWidths=[QW,QW,QW,QW])
        sum_t.setStyle(TableStyle([
            ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
            ('BACKGROUND',    (0,0),(-1,-1), GRAY_ROW),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('TOPPADDING',    (0,0),(-1,-1), 6),
            ('BOTTOMPADDING', (0,0),(-1,-1), 6),
            ('LEFTPADDING',   (0,0),(-1,-1), 0),
            ('RIGHTPADDING',  (0,0),(-1,-1), 0),
        ]))
        story.append(sum_t)
        story.append(Spacer(1, 4*mm))

        txs = month.get('transactions', [])
        if not txs:
            story.append(Paragraph(
                'Nenhum lançamento registrado neste mês.',
                ps(9, GRAY_TXT, align=TA_CENTER)
            ))
        else:
            # Cabeçalho da tabela
            tx_hdr = [
                Paragraph('Nº',          ps(8, WHITE, bold=True, align=TA_CENTER)),
                Paragraph('Data',        ps(8, WHITE, bold=True, align=TA_CENTER)),
                Paragraph('Tipo',        ps(8, WHITE, bold=True)),
                Paragraph('Descrição',   ps(8, WHITE, bold=True)),
                Paragraph('Valor',       ps(8, WHITE, bold=True, align=TA_RIGHT)),
                Paragraph('Comprovante', ps(8, WHITE, bold=True, align=TA_CENTER)),
            ]
            # Larguras iguais ao jsPDF:
            # Nº=10, Data=20, Tipo=32, Desc=auto, Valor=28, Comprovante=28
            NUM_W  = 10*mm
            DAT_W  = 20*mm
            TYP_W  = 32*mm
            VAL_W  = 28*mm
            CMP_W  = 28*mm
            DSC_W  = W - NUM_W - DAT_W - TYP_W - VAL_W - CMP_W

            tx_rows = [tx_hdr]
            for t in txs:
                nature = 'in' if t['transaction_type'] in INCOME else 'out'
                vc     = GREEN if nature == 'in' else RED_C
                sign   = '+ ' if nature == 'in' else '– '
                num    = global_tx_num.get(t['id'], '—')
                has_r  = bool(t.get('receipt_url'))
                tx_rows.append([
                    Paragraph(str(num), ps(7.5, BLACK, align=TA_CENTER)),
                    Paragraph(_fd(t['transaction_date']), ps(7.5, BLACK, align=TA_CENTER)),
                    Paragraph(TYPE_LABELS.get(t['transaction_type'], ''), ps(7.5, BLACK)),
                    Paragraph((t.get('description') or '')[:60], ps(7.5, BLACK)),
                    Paragraph(sign + _fc(t['amount']), ps(7.5, vc, bold=True, align=TA_RIGHT)),
                    Paragraph('✓' if has_r else '—', ps(7.5, GREEN if has_r else GRAY_TXT, align=TA_CENTER)),
                ])

            tx_t = Table(tx_rows, colWidths=[NUM_W, DAT_W, TYP_W, DSC_W, VAL_W, CMP_W])
            tx_style = [
                ('BACKGROUND',    (0,0),(-1,0), TC),
                ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
                ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
                ('TOPPADDING',    (0,0),(-1,-1), 3),
                ('BOTTOMPADDING', (0,0),(-1,-1), 3),
                ('LEFTPADDING',   (0,0),(-1,-1), 3),
                ('RIGHTPADDING',  (0,0),(-1,-1), 3),
            ]
            for ri in range(1, len(tx_rows)):
                if ri % 2 == 0:
                    tx_style.append(('BACKGROUND',(0,ri),(-1,ri), GRAY_ROW))
            tx_t.setStyle(TableStyle(tx_style))
            story.append(tx_t)

        # Rodapé da página do mês
        story.append(Spacer(1, 4*mm))
        story.append(HRFlowable(width=W, thickness=0.5, color=GRAY_LINE))
        story.append(Paragraph(
            f'{org_data.get("name","")} · Relatório Financeiro {year}',
            ps(6.5, GRAY_TXT, align=TA_CENTER)
        ))

    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════
# RELATÓRIO DE COMPROVANTES
# ═══════════════════════════════════════════════════════════════

def generate_receipts_report(
    org_data, period_data, months_data,
    b2_client, bucket_name, theme_color='#1a2a6c',
):
    buf = io.BytesIO()
    W_PAGE, H_PAGE = A4
    ML = MR = 14*mm
    W = W_PAGE - ML - MR

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=14*mm, bottomMargin=14*mm)

    TC = _theme(theme_color)
    year = period_data.get('fiscal_year')
    org_name = (org_data.get('name') or '').upper()
    story = []

    def ps(size=8, color=BLACK, bold=False, align=TA_LEFT, leading=None):
        return ParagraphStyle('_',
            fontSize=size, textColor=color,
            fontName='Helvetica-Bold' if bold else 'Helvetica',
            alignment=align, leading=leading or size*1.3,
            spaceAfter=0, spaceBefore=0)

    TYPE_LABELS = {
        'outras_receitas': 'Outras Receitas',
        'outras_despesas': 'Outras Despesas',
        'aci_recebida':    'ACI Recebida',
        'aci_enviada':     'ACI Enviada',
    }
    INCOME = {'outras_receitas', 'aci_recebida'}

    # ── Capa ──
    capa = Table([[
        Paragraph('RELATÓRIO DE COMPROVANTES', ps(14, WHITE, bold=True, align=TA_CENTER)),
        Paragraph(org_name, ps(10, WHITE, align=TA_CENTER)),
        Paragraph(f'Ano {year}', ps(9, WHITE, align=TA_CENTER)),
    ]], colWidths=[W])
    capa.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), TC),
        ('TOPPADDING',    (0,0),(-1,-1), 20),
        ('BOTTOMPADDING', (0,0),(-1,-1), 20),
        ('LEFTPADDING',   (0,0),(-1,-1), 8),
    ]))
    story.append(capa)
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(
        'Este relatório contém os comprovantes de todos os lançamentos do ano. '
        'Cada registro apresenta os dados do lançamento e a imagem do comprovante.',
        ps(9, GRAY_TXT, align=TA_CENTER)
    ))
    story.append(PageBreak())

    # ── Comprovantes ──
    # Numeração global igual ao relatório financeiro
    receipt_num = 0
    for month in months_data:
        for t in month.get('transactions', []):
            receipt_num += 1
            has_receipt = bool(t.get('receipt_url'))

            # Cabeçalho do comprovante
            hdr = Table([[
                Paragraph(
                    f'COMPROVANTE Nº {receipt_num:03d}',
                    ps(9, WHITE, bold=True)
                ),
                Paragraph(
                    f'{month["month_label"]} {year}',
                    ps(7.5, WHITE, align=TA_RIGHT)
                ),
            ]], colWidths=[W*0.6, W*0.4])
            hdr.setStyle(TableStyle([
                ('BACKGROUND',    (0,0),(-1,-1), TC),
                ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
                ('TOPPADDING',    (0,0),(-1,-1), 5),
                ('BOTTOMPADDING', (0,0),(-1,-1), 5),
                ('LEFTPADDING',   (0,0),(-1,-1), 8),
                ('RIGHTPADDING',  (0,0),(-1,-1), 8),
            ]))
            story.append(hdr)
            story.append(Spacer(1, 2*mm))

            # Dados do lançamento
            nature = 'in' if t['transaction_type'] in INCOME else 'out'
            vc     = GREEN if nature == 'in' else RED_C
            sign   = '+ ' if nature == 'in' else '– '
            LW2 = 28*mm
            HW2 = W / 2
            VW2 = HW2 - LW2

            info_t = Table([
                [
                    Paragraph('DATA', ps(7, GRAY_TXT, align=TA_RIGHT)),
                    Paragraph(_fd(t['transaction_date']), ps(8, BLACK)),
                    Paragraph('TIPO', ps(7, GRAY_TXT, align=TA_RIGHT)),
                    Paragraph(TYPE_LABELS.get(t['transaction_type'],''), ps(8, BLACK)),
                ],
                [
                    Paragraph('DESCRIÇÃO', ps(7, GRAY_TXT, align=TA_RIGHT)),
                    Paragraph(t.get('description',''), ps(8, BLACK)),
                    Paragraph('VALOR', ps(7, GRAY_TXT, align=TA_RIGHT)),
                    Paragraph(sign + _fc(t['amount']), ps(9, vc, bold=True)),
                ],
            ], colWidths=[LW2, VW2, LW2, VW2])
            info_t.setStyle(TableStyle([
                ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
                ('BACKGROUND',    (0,0),(-1,-1), GRAY_ROW),
                ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
                ('TOPPADDING',    (0,0),(-1,-1), 4),
                ('BOTTOMPADDING', (0,0),(-1,-1), 4),
                ('LEFTPADDING',   (0,0),(-1,-1), 4),
                ('RIGHTPADDING',  (0,0),(-1,-1), 4),
            ]))
            story.append(info_t)
            story.append(Spacer(1, 3*mm))

            # Imagem do comprovante
            if has_receipt:
                img_bytes, ct = _download_b2(b2_client, bucket_name, t['receipt_url'])
                if img_bytes and ct != 'application/pdf' and not t['receipt_url'].lower().endswith('.pdf'):
                    try:
                        from PIL import Image as PILImg
                        pil = PILImg.open(io.BytesIO(img_bytes))
                        ow, oh = pil.size
                        MAX_W = W
                        MAX_H = 185*mm
                        ratio = min(MAX_W/(ow*0.352778), MAX_H/(oh*0.352778))
                        iw = ow * 0.352778 * ratio
                        ih = oh * 0.352778 * ratio
                        img_buf = io.BytesIO(img_bytes)
                        rl_img = Image(img_buf, width=iw, height=ih)
                        rl_img.hAlign = 'CENTER'
                        frame = Table([[rl_img]], colWidths=[W])
                        frame.setStyle(TableStyle([
                            ('BOX',           (0,0),(-1,-1), 1, GRAY_LINE),
                            ('TOPPADDING',    (0,0),(-1,-1), 4),
                            ('BOTTOMPADDING', (0,0),(-1,-1), 4),
                            ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
                        ]))
                        story.append(frame)
                    except Exception as e:
                        story.append(Paragraph(f'Erro ao carregar imagem: {e}',
                                               ps(8, RED_C, align=TA_CENTER)))
                elif img_bytes:
                    story.append(Paragraph(
                        'Comprovante em formato PDF — arquivo original mantido no armazenamento.',
                        ps(9, GRAY_TXT, align=TA_CENTER)
                    ))
                else:
                    story.append(Paragraph('Comprovante não disponível.',
                                           ps(9, GRAY_TXT, align=TA_CENTER)))
            else:
                story.append(Paragraph('Nenhum comprovante anexado a este lançamento.',
                                       ps(9, GRAY_TXT, align=TA_CENTER)))

            story.append(Spacer(1, 3*mm))
            story.append(HRFlowable(width=W, thickness=0.5, color=GRAY_LINE))
            story.append(Paragraph(
                f'Comprovante {receipt_num:03d} · {org_data.get("name","")} · {year}',
                ps(6.5, GRAY_TXT, align=TA_CENTER)
            ))
            story.append(PageBreak())

    if receipt_num == 0:
        story.append(Paragraph(
            'Nenhum comprovante encontrado para este período.',
            ps(11, GRAY_TXT, align=TA_CENTER)
        ))

    doc.build(story)
    return buf.getvalue()