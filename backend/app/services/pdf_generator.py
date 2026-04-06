import io
import re
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Image
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import KeepTogether


# ── Cores da marca ──
BLUE_DARK  = colors.HexColor('#1a2a6c')
BLUE_MED   = colors.HexColor('#2a3f9f')
ORANGE     = colors.HexColor('#e8630a')
GREEN      = colors.HexColor('#16a34a')
RED        = colors.HexColor('#dc2626')
GRAY_LIGHT = colors.HexColor('#f5f7fa')
GRAY_MED   = colors.HexColor('#e2e8f0')
WHITE      = colors.white
BLACK      = colors.HexColor('#1e293b')


def fmt_currency(value):
    try:
        return f"R$ {float(value):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except:
        return "R$ 0,00"


def fmt_date(date_val):
    if not date_val:
        return '—'
    if isinstance(date_val, str):
        try:
            parts = date_val.split('T')[0].split('-')
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
        except:
            return date_val
    try:
        return date_val.strftime('%d/%m/%Y')
    except:
        return str(date_val)


def month_label(month: int) -> str:
    labels = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
              "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
    return labels[month - 1]


def _get_theme_color(hex_color: str):
    try:
        return colors.HexColor(hex_color)
    except:
        return BLUE_DARK


def _download_image_from_b2(client, bucket_name: str, receipt_url: str):
    """Baixa imagem do B2 e retorna bytes ou None"""
    try:
        match = re.search(rf'/file/{re.escape(bucket_name)}/(.+)$', receipt_url)
        if not match:
            match = re.search(rf'/{re.escape(bucket_name)}/(.+)$', receipt_url)
        if not match:
            return None, None
        key = match.group(1)
        response = client.get_object(Bucket=bucket_name, Key=key)
        content_type = response.get('ContentType', 'image/png')
        image_bytes = response['Body'].read()
        return image_bytes, content_type
    except Exception as e:
        print(f"Erro ao baixar imagem: {e}")
        return None, None


# ════════════════════════════════════════════════════════
# RELATÓRIO FINANCEIRO
# ════════════════════════════════════════════════════════

def generate_financial_report(
    org_data: dict,
    period_data: dict,
    months_data: list,
    board_data: list,
    logo_bytes: bytes = None,
    logo_content_type: str = None,
    theme_color: str = '#1a2a6c',
) -> bytes:
    """Gera o relatório financeiro em PDF e retorna bytes"""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
        title=f"Relatório Financeiro {period_data.get('fiscal_year')}",
    )

    theme = _get_theme_color(theme_color)
    styles = getSampleStyleSheet()
    story = []

    W = A4[0] - 30*mm  # largura útil

    # ── Cabeçalho ──
    header_data = [[]]

    # Logo
    if logo_bytes:
        try:
            img_buf = io.BytesIO(logo_bytes)
            logo_img = Image(img_buf, width=28*mm, height=28*mm)
            logo_img.hAlign = 'LEFT'
            header_data[0].append(logo_img)
        except:
            header_data[0].append(Paragraph('', styles['Normal']))
    else:
        header_data[0].append(Paragraph('', styles['Normal']))

    # Título central
    org_name = (org_data.get('name') or '').upper()
    year = period_data.get('fiscal_year')
    title_para = Paragraph(
        f'<font color="#ffffff" size="8">RELATÓRIO FINANCEIRO</font><br/>'
        f'<font color="#ffffff" size="13"><b>{org_name}</b></font><br/>'
        f'<font color="#aabbdd" size="8">Ano {year}</font>',
        ParagraphStyle('center', alignment=TA_CENTER, leading=16)
    )
    header_data[0].append(title_para)
    header_data[0].append(Paragraph('', styles['Normal']))

    col_widths = [32*mm, W - 64*mm, 32*mm]
    header_table = Table(header_data, colWidths=col_widths)
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (1, 0), (1, 0), theme),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('LEFTPADDING', (1, 0), (1, 0), 6),
        ('RIGHTPADDING', (1, 0), (1, 0), 6),
        ('TOPPADDING', (1, 0), (1, 0), 8),
        ('BOTTOMPADDING', (1, 0), (1, 0), 8),
        ('ROWHEIGHT', (0, 0), (-1, -1), 32*mm),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4*mm))

    # ── Seção: Informações Gerais ──
    def section_header(title):
        t = Table([[Paragraph(f'<b><font color="white" size="9">{title}</font></b>',
                    ParagraphStyle('sh', alignment=TA_CENTER))]],
                  colWidths=[W])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), theme),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        return t

    def info_row(label, value, shade=False):
        lbl_style = ParagraphStyle('lbl', fontSize=7, textColor=colors.HexColor('#64748b'), alignment=TA_RIGHT)
        val_style = ParagraphStyle('val', fontSize=8, textColor=BLACK)
        return [Paragraph(label.upper(), lbl_style), Paragraph(str(value or '—'), val_style)]

    def info_row2(l1, v1, l2, v2, shade=False):
        lbl = ParagraphStyle('lbl', fontSize=7, textColor=colors.HexColor('#64748b'), alignment=TA_RIGHT)
        val = ParagraphStyle('val', fontSize=8, textColor=BLACK)
        return [
            Paragraph(l1.upper(), lbl), Paragraph(str(v1 or '—'), val),
            Paragraph(l2.upper(), lbl), Paragraph(str(v2 or '—'), val),
        ]

    story.append(section_header('INFORMAÇÕES GERAIS'))
    story.append(Spacer(1, 1*mm))
    story.append(section_header('IDENTIFICAÇÃO DA ORGANIZAÇÃO'))

    society_type = org_data.get('society_type', 'UMP')
    is_fed = org_data.get('organization_type') == 'federation'
    org_label = 'FEDERAÇÃO' if is_fed else society_type

    lw = 45*mm
    vw = W - lw
    half = W / 2

    rows_id = []
    rows_id.append(info_row(org_label, (org_data.get('name') or '').upper()))
    rows_id.append(info_row('PRESBITÉRIO', (org_data.get('presbytery_name') or '').upper(), True))
    if not is_fed:
        rows_id.append(info_row('IGREJA', (org_data.get('church_name') or '').upper()))
        rows_id.append(info_row('PASTOR', org_data.get('pastor_name') or '—', True))
    rows_id.append(info_row2(
        'ANO VIGENTE', year,
        'DATA DO RELATÓRIO', datetime.date.today().strftime('%d/%m/%Y'),
        shade=len(rows_id) % 2 == 0
    ))

    presidente = next((b for b in board_data if b.get('role') == 'presidente'), None)
    tesoureiro = next((b for b in board_data if b.get('role') == 'tesoureiro'), None)
    rows_id.append(info_row('PRESIDENTE', (presidente.get('member_name') or '—').upper() if presidente else '—',
                            shade=len(rows_id) % 2 == 0))
    rows_id.append(info_row('TESOUREIRO(A)', (tesoureiro.get('member_name') or '—').upper() if tesoureiro else '—',
                            shade=len(rows_id) % 2 == 0))

    id_table_data = list(rows_id)
    id_table = Table(id_table_data, colWidths=[lw, vw])
    style_cmds = [
        ('GRID', (0,0), (-1,-1), 0.5, GRAY_MED),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]
    for i in range(len(rows_id)):
        if i % 2 == 1:
            style_cmds.append(('BACKGROUND', (0,i), (-1,i), GRAY_LIGHT))
    id_table.setStyle(TableStyle(style_cmds))
    story.append(id_table)
    story.append(Spacer(1, 3*mm))

    # ── Informações Financeiras ──
    story.append(section_header(f'INFORMAÇÕES FINANCEIRAS {year}'))

    total_in  = sum(float(m.get('total_in', 0)) for m in months_data)
    total_out = sum(float(m.get('total_out', 0)) for m in months_data)
    aci_in    = sum(
        sum(float(t['amount']) for t in m.get('transactions', []) if t['transaction_type'] == 'aci_recebida')
        for m in months_data
    )
    aci_out   = sum(
        sum(float(t['amount']) for t in m.get('transactions', []) if t['transaction_type'] == 'aci_enviada')
        for m in months_data
    )
    outras_rec = total_in - aci_in
    outras_des = total_out - aci_out

    initial_balance = float(period_data.get('initial_balance', 0))
    final_balance   = float(period_data.get('final_balance', 0))

    half_w = W / 2
    lbl7  = ParagraphStyle('l7', fontSize=7.5, textColor=BLACK)
    val7r = ParagraphStyle('v7r', fontSize=7.5, textColor=BLACK, alignment=TA_RIGHT)
    bold7 = ParagraphStyle('b7', fontSize=7.5, textColor=BLACK, fontName='Helvetica-Bold')
    bold7r = ParagraphStyle('b7r', fontSize=7.5, textColor=BLACK, fontName='Helvetica-Bold', alignment=TA_RIGHT)

    def fin_hdr(txt):
        return Paragraph(f'<b><font color="white" size="7.5">{txt}</font></b>',
                         ParagraphStyle('fh', alignment=TA_CENTER))

    fin_data = [
        [Paragraph(f'<b><font color="white">SALDO DO ANO ANTERIOR {year-1}</font></b>',
                   ParagraphStyle('', fontSize=8, textColor=WHITE, fontName='Helvetica-Bold')),
         Paragraph(fmt_currency(initial_balance),
                   ParagraphStyle('', fontSize=8, textColor=WHITE, alignment=TA_RIGHT)),
         Paragraph('', styles['Normal']),
         Paragraph('', styles['Normal'])],

        [fin_hdr(f'RECEITAS ({year})'), fin_hdr(''), fin_hdr(f'DESPESAS ({year})'), fin_hdr('')],

        [Paragraph('ACI Recebida', lbl7), Paragraph(fmt_currency(aci_in), val7r),
         Paragraph('ACI Enviada', lbl7), Paragraph(fmt_currency(aci_out), val7r)],

        [Paragraph('Outras Receitas (+)', lbl7), Paragraph(fmt_currency(outras_rec), val7r),
         Paragraph('Outras Despesas (−)', lbl7), Paragraph(fmt_currency(outras_des), val7r)],

        [Paragraph('TOTAL RECEITA ANUAL', bold7), Paragraph(fmt_currency(total_in), bold7r),
         Paragraph('TOTAL DESPESA ANUAL', bold7), Paragraph(fmt_currency(total_out), bold7r)],

        [Paragraph(f'TOTAL GERAL (SALDO + RECEITAS)', bold7),
         Paragraph(fmt_currency(initial_balance + total_in), bold7r),
         Paragraph(f'SALDO FINAL PARA {year+1}', bold7),
         Paragraph(fmt_currency(final_balance), bold7r)],
    ]

    fin_table = Table(fin_data, colWidths=[half_w*0.55, half_w*0.45, half_w*0.55, half_w*0.45])
    fin_style = [
        ('GRID', (0,0), (-1,-1), 0.5, GRAY_MED),
        ('BACKGROUND', (0,0), (1,0), theme),
        ('SPAN', (0,0), (1,0)),
        ('BACKGROUND', (0,1), (1,1), theme),
        ('BACKGROUND', (2,1), (3,1), theme),
        ('BACKGROUND', (2,0), (3,0), colors.HexColor('#f1f5f9')),
        ('BACKGROUND', (0,2), (-1,2), GRAY_LIGHT),
        ('BACKGROUND', (0,4), (-1,4), GRAY_LIGHT),
        ('BACKGROUND', (0,5), (-1,5), GRAY_LIGHT),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]
    fin_table.setStyle(TableStyle(fin_style))
    story.append(fin_table)
    story.append(Spacer(1, 4*mm))

    # ── Área de observações ──
    obs_data = [[
        Paragraph('<b>OBSERVAÇÕES:</b>', ParagraphStyle('obs', fontSize=7)),
        Paragraph('<b>OBSERVAÇÕES:</b>', ParagraphStyle('obs', fontSize=7)),
    ]]
    obs_table = Table(obs_data, colWidths=[half_w-1*mm, half_w-1*mm], rowHeights=[22*mm])
    obs_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, GRAY_MED),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#fffde7')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(obs_table)
    story.append(Spacer(1, 6*mm))

    # ── Assinaturas ──
    sig_w = (W - 20*mm) / 2
    sig_style = ParagraphStyle('sig', alignment=TA_CENTER, fontSize=8)
    sig_bold  = ParagraphStyle('sigb', alignment=TA_CENTER, fontSize=8, fontName='Helvetica-Bold')
    sig_name  = ParagraphStyle('sign', alignment=TA_CENTER, fontSize=9, fontName='Helvetica-Bold')

    pres_name = (presidente.get('member_name') or '').upper() if presidente else '___________________'
    tes_name  = (tesoureiro.get('member_name') or '').upper() if tesoureiro else '___________________'

    sig_data = [[
        Table([
            [HRFlowable(width=sig_w, thickness=1, color=BLACK)],
            [Paragraph(pres_name, sig_name)],
            [Paragraph('Presidente da', sig_style)],
            [Paragraph((org_data.get('name') or '').upper(), sig_bold)],
        ], colWidths=[sig_w]),
        Spacer(20*mm, 1),
        Table([
            [HRFlowable(width=sig_w, thickness=1, color=BLACK)],
            [Paragraph(tes_name, sig_name)],
            [Paragraph('Tesoureiro(a) da', sig_style)],
            [Paragraph((org_data.get('name') or '').upper(), sig_bold)],
        ], colWidths=[sig_w]),
    ]]
    sig_table = Table(sig_data, colWidths=[sig_w, 20*mm, sig_w])
    sig_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(sig_table)
    story.append(Spacer(1, 6*mm))

    # ── Rodapé da capa ──
    footer_data = [[Paragraph(
        f'<b><font color="white">{(org_data.get("name") or "").upper()} — {org_data.get("presbytery_name") or ""}</font></b>',
        ParagraphStyle('ft', alignment=TA_CENTER, fontSize=8)
    )]]
    footer_table = Table(footer_data, colWidths=[W])
    footer_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), theme),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(footer_table)

    # ── Páginas dos meses ──
    for month in months_data:
        story.append(PageBreak())

        # Cabeçalho do mês
        mhdr_data = [[]]
        if logo_bytes:
            try:
                img_buf = io.BytesIO(logo_bytes)
                mhdr_data[0].append(Image(img_buf, width=20*mm, height=20*mm))
            except:
                mhdr_data[0].append(Paragraph('', styles['Normal']))
        else:
            mhdr_data[0].append(Paragraph('', styles['Normal']))

        month_title = f"{month['month_label'].upper()} {year}"
        mhdr_data[0].append(Paragraph(
            f'<font color="#aabbdd" size="7">{org_data.get("name","")}</font><br/>'
            f'<font color="white" size="12"><b>{month_title}</b></font><br/>'
            f'<font color="#aabbdd" size="6">Relatório Financeiro Mensal</font>',
            ParagraphStyle('mc', alignment=TA_CENTER, leading=14)
        ))
        mhdr_data[0].append(Paragraph('', styles['Normal']))

        mhdr_table = Table(mhdr_data, colWidths=[24*mm, W - 48*mm, 24*mm])
        mhdr_table.setStyle(TableStyle([
            ('BACKGROUND', (1,0), (1,0), theme),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (1,0), (1,0), 'CENTER'),
            ('TOPPADDING', (1,0), (1,0), 6),
            ('BOTTOMPADDING', (1,0), (1,0), 6),
            ('ROWHEIGHT', (0,0), (-1,-1), 24*mm),
        ]))
        story.append(mhdr_table)
        story.append(Spacer(1, 3*mm))

        # Resumo do mês
        qw = W / 4
        summary_data = [[
            Paragraph(f'<font size="6" color="#94a3b8">SALDO ANTERIOR</font><br/><b>{fmt_currency(month["opening_balance"])}</b>',
                      ParagraphStyle('ms', alignment=TA_CENTER, leading=12, fontSize=8)),
            Paragraph(f'<font size="6" color="#94a3b8">ENTRADAS</font><br/><b><font color="#16a34a">{fmt_currency(month["total_in"])}</font></b>',
                      ParagraphStyle('ms', alignment=TA_CENTER, leading=12, fontSize=8)),
            Paragraph(f'<font size="6" color="#94a3b8">SAÍDAS</font><br/><b><font color="#dc2626">{fmt_currency(month["total_out"])}</font></b>',
                      ParagraphStyle('ms', alignment=TA_CENTER, leading=12, fontSize=8)),
            Paragraph(f'<font size="6" color="#94a3b8">SALDO DO MÊS</font><br/><b><font color="#1a2a6c">{fmt_currency(month["closing_balance"])}</font></b>',
                      ParagraphStyle('ms', alignment=TA_CENTER, leading=12, fontSize=8)),
        ]]
        summary_table = Table(summary_data, colWidths=[qw, qw, qw, qw])
        summary_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, GRAY_MED),
            ('BACKGROUND', (0,0), (-1,-1), GRAY_LIGHT),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 3*mm))

        # Tabela de lançamentos
        if not month.get('transactions'):
            story.append(Paragraph(
                '<i>Nenhum lançamento registrado neste mês.</i>',
                ParagraphStyle('empty', alignment=TA_CENTER, fontSize=9, textColor=colors.HexColor('#94a3b8'))
            ))
        else:
            tx_header = [
                Paragraph('<b><font color="white" size="7">Nº</font></b>', ParagraphStyle('th', alignment=TA_CENTER)),
                Paragraph('<b><font color="white" size="7">DATA</font></b>', ParagraphStyle('th', alignment=TA_CENTER)),
                Paragraph('<b><font color="white" size="7">TIPO</font></b>', ParagraphStyle('th')),
                Paragraph('<b><font color="white" size="7">DESCRIÇÃO</font></b>', ParagraphStyle('th')),
                Paragraph('<b><font color="white" size="7">VALOR</font></b>', ParagraphStyle('th', alignment=TA_RIGHT)),
            ]
            tx_rows = [tx_header]
            type_labels = {
                'outras_receitas': 'Outras Receitas',
                'outras_despesas': 'Outras Despesas',
                'aci_recebida':    'ACI Recebida',
                'aci_enviada':     'ACI Enviada',
            }
            for i, t in enumerate(month['transactions']):
                nature = 'in' if t['transaction_type'] in ('outras_receitas', 'aci_recebida') else 'out'
                value_color = '#16a34a' if nature == 'in' else '#dc2626'
                sign = '+' if nature == 'in' else '–'
                tx_rows.append([
                    Paragraph(str(i+1), ParagraphStyle('tc', alignment=TA_CENTER, fontSize=7)),
                    Paragraph(fmt_date(t['transaction_date']), ParagraphStyle('tc', alignment=TA_CENTER, fontSize=7)),
                    Paragraph(type_labels.get(t['transaction_type'], t['transaction_type']), ParagraphStyle('tc', fontSize=7)),
                    Paragraph(t['description'][:60], ParagraphStyle('tc', fontSize=7)),
                    Paragraph(f'{sign} {fmt_currency(t["amount"])}',
                              ParagraphStyle('tc', alignment=TA_RIGHT, fontSize=7,
                                             textColor=colors.HexColor(value_color))),
                ])

            tx_table = Table(tx_rows, colWidths=[10*mm, 20*mm, 32*mm, W-95*mm, 33*mm])
            tx_style = [
                ('BACKGROUND', (0,0), (-1,0), theme),
                ('GRID', (0,0), (-1,-1), 0.5, GRAY_MED),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('TOPPADDING', (0,0), (-1,-1), 3),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
                ('LEFTPADDING', (0,0), (-1,-1), 3),
                ('RIGHTPADDING', (0,0), (-1,-1), 3),
            ]
            for i in range(1, len(tx_rows)):
                if i % 2 == 0:
                    tx_style.append(('BACKGROUND', (0,i), (-1,i), GRAY_LIGHT))
            tx_table.setStyle(TableStyle(tx_style))
            story.append(tx_table)

        # Rodapé da página do mês
        story.append(Spacer(1, 4*mm))
        story.append(HRFlowable(width=W, thickness=0.5, color=GRAY_MED))
        story.append(Paragraph(
            f'<font size="6" color="#94a3b8">{org_data.get("name","")} · Relatório Financeiro {year}</font>',
            ParagraphStyle('pft', alignment=TA_CENTER)
        ))

    doc.build(story)
    return buffer.getvalue()


# ════════════════════════════════════════════════════════
# RELATÓRIO DE COMPROVANTES
# ════════════════════════════════════════════════════════

def generate_receipts_report(
    org_data: dict,
    period_data: dict,
    months_data: list,
    b2_client,
    bucket_name: str,
    theme_color: str = '#1a2a6c',
) -> bytes:
    """Gera relatório com imagem de cada comprovante"""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
        title=f"Comprovantes {period_data.get('fiscal_year')}",
    )

    theme = _get_theme_color(theme_color)
    styles = getSampleStyleSheet()
    story = []
    W = A4[0] - 30*mm
    year = period_data.get('fiscal_year')

    # ── Capa dos comprovantes ──
    capa = Table([[
        Paragraph(
            f'<b><font color="white" size="14">COMPROVANTES</font></b><br/>'
            f'<font color="#aabbdd" size="10">{(org_data.get("name") or "").upper()}</font><br/>'
            f'<font color="#aabbdd" size="9">Ano {year}</font>',
            ParagraphStyle('cv', alignment=TA_CENTER, leading=18)
        )
    ]], colWidths=[W])
    capa.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), theme),
        ('TOPPADDING', (0,0), (-1,-1), 20),
        ('BOTTOMPADDING', (0,0), (-1,-1), 20),
    ]))
    story.append(capa)
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph(
        'Este relatório contém os comprovantes de todos os lançamentos financeiros do ano. '
        'Cada página apresenta os dados do lançamento e a imagem do comprovante correspondente.',
        ParagraphStyle('intro', fontSize=9, alignment=TA_CENTER,
                       textColor=colors.HexColor('#64748b'))
    ))
    story.append(PageBreak())

    # ── Uma página por comprovante ──
    receipt_num = 0
    type_labels = {
        'outras_receitas': 'Outras Receitas',
        'outras_despesas': 'Outras Despesas',
        'aci_recebida':    'ACI Recebida',
        'aci_enviada':     'ACI Enviada',
    }

    for month in months_data:
        for t in month.get('transactions', []):
            if not t.get('receipt_url'):
                continue

            receipt_num += 1

            # Baixa a imagem do B2
            img_bytes, content_type = _download_image_from_b2(b2_client, bucket_name, t['receipt_url'])

            # Cabeçalho do comprovante
            nature = 'in' if t['transaction_type'] in ('outras_receitas', 'aci_recebida') else 'out'
            value_color = '#16a34a' if nature == 'in' else '#dc2626'
            sign = '+' if nature == 'in' else '–'

            hdr = Table([[
                Paragraph(
                    f'<b><font color="white" size="8">COMPROVANTE Nº {receipt_num:03d}</font></b><br/>'
                    f'<font color="#aabbdd" size="7">{month["month_label"]} {year}</font>',
                    ParagraphStyle('ch', leading=12)
                )
            ]], colWidths=[W])
            hdr.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), theme),
                ('TOPPADDING', (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                ('LEFTPADDING', (0,0), (-1,-1), 8),
            ]))
            story.append(hdr)
            story.append(Spacer(1, 2*mm))

            # Dados do lançamento
            lbl = ParagraphStyle('lbl', fontSize=7, textColor=colors.HexColor('#64748b'), alignment=TA_RIGHT)
            val = ParagraphStyle('val', fontSize=8, textColor=BLACK)
            valbold = ParagraphStyle('vb', fontSize=9, fontName='Helvetica-Bold',
                                     textColor=colors.HexColor(value_color))

            info_data = [
                [Paragraph('DATA', lbl), Paragraph(fmt_date(t['transaction_date']), val),
                 Paragraph('TIPO', lbl), Paragraph(type_labels.get(t['transaction_type'], ''), val)],
                [Paragraph('DESCRIÇÃO', lbl), Paragraph(t['description'], val),
                 Paragraph('VALOR', lbl), Paragraph(f'{sign} {fmt_currency(t["amount"])}', valbold)],
            ]
            lw2 = 25*mm
            vw2 = W/2 - lw2
            info_table = Table(info_data, colWidths=[lw2, vw2, lw2, vw2])
            info_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 0.5, GRAY_MED),
                ('BACKGROUND', (0,0), (-1,-1), GRAY_LIGHT),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('LEFTPADDING', (0,0), (-1,-1), 4),
                ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 3*mm))

            # Imagem do comprovante
            if img_bytes:
                try:
                    if content_type == 'application/pdf' or t['receipt_url'].lower().endswith('.pdf'):
                        story.append(Paragraph(
                            '<i>Comprovante em formato PDF — consulte o arquivo original.</i>',
                            ParagraphStyle('pdf_note', alignment=TA_CENTER, fontSize=9,
                                           textColor=colors.HexColor('#64748b'))
                        ))
                    else:
                        from PIL import Image as PILImage
                        pil_img = PILImage.open(io.BytesIO(img_bytes))

                        max_w = W
                        max_h = 180*mm
                        orig_w, orig_h = pil_img.size
                        ratio = min(max_w / (orig_w * 0.352778), max_h / (orig_h * 0.352778))
                        img_w = orig_w * 0.352778 * ratio
                        img_h = orig_h * 0.352778 * ratio

                        img_buf = io.BytesIO(img_bytes)
                        rl_img = Image(img_buf, width=img_w, height=img_h)
                        rl_img.hAlign = 'CENTER'

                        img_frame = Table([[rl_img]], colWidths=[W])
                        img_frame.setStyle(TableStyle([
                            ('BOX', (0,0), (-1,-1), 1, GRAY_MED),
                            ('TOPPADDING', (0,0), (-1,-1), 4),
                            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                        ]))
                        story.append(img_frame)
                except Exception as e:
                    story.append(Paragraph(
                        '<i>Erro ao carregar imagem do comprovante.</i>',
                        ParagraphStyle('err', alignment=TA_CENTER, fontSize=9,
                                       textColor=colors.HexColor('#dc2626'))
                    ))
            else:
                story.append(Paragraph(
                    '<i>Comprovante não disponível.</i>',
                    ParagraphStyle('na', alignment=TA_CENTER, fontSize=9,
                                   textColor=colors.HexColor('#94a3b8'))
                ))

            story.append(Spacer(1, 3*mm))
            story.append(HRFlowable(width=W, thickness=0.5, color=GRAY_MED))
            story.append(Paragraph(
                f'<font size="6" color="#94a3b8">Comprovante {receipt_num:03d} · {org_data.get("name","")} · {year}</font>',
                ParagraphStyle('pft', alignment=TA_CENTER)
            ))
            story.append(PageBreak())

    if receipt_num == 0:
        story.append(Paragraph(
            'Nenhum comprovante encontrado para este período.',
            ParagraphStyle('none', alignment=TA_CENTER, fontSize=11,
                           textColor=colors.HexColor('#94a3b8'))
        ))

    doc.build(story)
    return buffer.getvalue()
