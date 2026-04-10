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


GRAY_ROW  = colors.HexColor('#f5f7fa')
GRAY_LINE = colors.HexColor('#e2e8f0')
GRAY_TXT  = colors.HexColor('#64748b')
BLACK     = colors.HexColor('#1e293b')
GREEN     = colors.HexColor('#16a34a')
RED_C     = colors.HexColor('#dc2626')
WHITE     = colors.white
YELLOW_BG = colors.HexColor('#fffde7')
BLUE_DEF  = colors.HexColor('#1a2a6c')


def _tc(hex_color):
    try:
        return colors.HexColor(str(hex_color))
    except:
        return BLUE_DEF


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


def _ps(size=8, color=BLACK, bold=False, align=TA_LEFT):
    return ParagraphStyle('_',
        fontSize=size,
        textColor=color,
        fontName='Helvetica-Bold' if bold else 'Helvetica',
        alignment=align,
        leading=size * 1.4,
        spaceAfter=0, spaceBefore=0,
    )


def _logo(logo_bytes, w_mm, h_mm):
    if not logo_bytes:
        return None
    try:
        img = Image(io.BytesIO(logo_bytes), width=w_mm*mm, height=h_mm*mm)
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
        return resp['Body'].read(), resp.get('ContentType', 'image/png')
    except:
        return None, None


MONTHS = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
          'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

TYPE_LABELS = {
    'outras_receitas': 'Outras Receitas',
    'outras_despesas': 'Outras Despesas',
    'aci_recebida':    'ACI Recebida',
    'aci_enviada':     'ACI Enviada',
}
INCOME = {'outras_receitas', 'aci_recebida'}


def _section_bar(text, W, TC):
    t = Table(
        [[Paragraph(text, _ps(9, WHITE, bold=True, align=TA_CENTER))]],
        colWidths=[W], rowHeights=[7*mm]
    )
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), TC),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 0),
        ('BOTTOMPADDING', (0,0),(-1,-1), 0),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
    ]))
    return t


# ═══════════════════════════════════════════════════════════════
# REGISTRO DE ATOS (SECRETARIA)
# ═══════════════════════════════════════════════════════════════

def generate_meeting_report(
    meeting_data: dict,
    org_data: dict,
    logo_bytes: bytes = None,
    ipb_logo_bytes: bytes = None,
    theme_color: str = '#1a2a6c',
) -> bytes:
    """Gera o PDF do Registro de Atos no modelo oficial."""

    buf = io.BytesIO()
    ML = MR = 15 * mm
    MT = MB = 15 * mm
    W = A4[0] - ML - MR

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB)

    TC = _tc(theme_color)
    story = []

    # ── Cabeçalho com logos ──────────────────────────────────
    org_name = (org_data.get('name') or '').upper()

    ipb_cell = Spacer(22 * mm, 22 * mm)
    if ipb_logo_bytes:
        try:
            ipb_cell = Image(io.BytesIO(ipb_logo_bytes), width=22 * mm, height=22 * mm)
        except Exception:
            pass

    org_cell = Spacer(22 * mm, 22 * mm)
    if logo_bytes:
        try:
            org_cell = Image(io.BytesIO(logo_bytes), width=22 * mm, height=22 * mm)
        except Exception:
            pass

    title_w = W - 44 * mm
    title_content = Table([
        [Paragraph('IGREJA PRESBITERIANA DO BRASIL',
                   _ps(9, BLACK, bold=True, align=TA_CENTER))],
        [Spacer(1, 1 * mm)],
        [Paragraph(org_name, _ps(10, BLACK, bold=True, align=TA_CENTER))],
    ], colWidths=[title_w])
    title_content.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    hdr = Table([[ipb_cell, title_content, org_cell]],
                colWidths=[22 * mm, title_w, 22 * mm])
    hdr.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
        ('TOPPADDING',    (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width=W, thickness=1, color=GRAY_LINE))
    story.append(Spacer(1, 3 * mm))

    # ── Tabela de identificação ──────────────────────────────
    def fmt_dt(dt_str):
        if not dt_str:
            return '—'
        try:
            dt = datetime.datetime.fromisoformat(dt_str)
            return dt.strftime('%d/%m/%Y %H:%M')
        except Exception:
            return dt_str

    HW = W / 2
    id_data = [
        [
            Paragraph(f'<b>Registro de Atos Nº {meeting_data.get("record_number", "")}</b>',
                      _ps(8.5, BLACK, bold=True)),
            Paragraph(f'<b>{meeting_data.get("meeting_type", "")}</b>',
                      _ps(8.5, BLACK, bold=True)),
        ],
        [
            Paragraph(f'<b>Início:</b> {fmt_dt(meeting_data.get("started_at"))}', _ps(8.5, BLACK)),
            Paragraph(f'<b>Término:</b> {fmt_dt(meeting_data.get("ended_at"))}', _ps(8.5, BLACK)),
        ],
        [
            Paragraph(f'<b>Local:</b> {meeting_data.get("location_name") or "—"}', _ps(8.5, BLACK)),
            Paragraph(f'<b>Cidade/UF:</b> {meeting_data.get("city") or "—"}/{meeting_data.get("state") or "—"}', _ps(8.5, BLACK)),
        ],
        [
            Paragraph(f'<b>Endereço:</b> {meeting_data.get("address") or "—"}', _ps(8.5, BLACK)),
            Paragraph('', _ps()),
        ],
        [
            Paragraph(f'<b>Presidente da Reunião:</b> {meeting_data.get("meeting_president") or "—"}', _ps(8.5, BLACK)),
            Paragraph('', _ps()),
        ],
    ]

    id_table = Table(id_data, colWidths=[HW, HW])
    id_table.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 1, BLACK),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, GRAY_LINE),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
        ('SPAN',          (0, 3), (-1, 3)),
        ('SPAN',          (0, 4), (-1, 4)),
    ]))
    story.append(id_table)
    story.append(Spacer(1, 4 * mm))

    # ── Helpers internos ─────────────────────────────────────
    def _sec_title(txt):
        t = Table(
            [[Paragraph(f'<b>{txt}</b>', _ps(9, WHITE, bold=True, align=TA_CENTER))]],
            colWidths=[W],
        )
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), TC),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ]))
        return t

    def _bold(txt):
        return Paragraph(f'<b>{txt}</b>', _ps(8.5, BLACK, bold=True))

    def _item(txt, indent_mm=4):
        return Paragraph(txt, ParagraphStyle('_i',
            fontSize=8.5, textColor=BLACK, fontName='Helvetica',
            leading=12, leftIndent=indent_mm * mm, spaceAfter=1,
        ))

    # ── PRESENTES ────────────────────────────────────────────
    story.append(_sec_title('PRESENTES'))
    story.append(Spacer(1, 2 * mm))

    attendees = meeting_data.get('attendees', [])
    present = [a for a in attendees if a.get('is_present')]
    absent  = [a for a in attendees if not a.get('is_present')]

    org_type = org_data.get('organization_type', 'federation')
    presb_label = 'Conselheiro(a)' if org_type == 'local_ump' else 'Secretário Presbiterial'

    def _cnt(tp):
        return sum(1 for a in present if a.get('attendee_type') == tp)

    total       = len(present)
    del_count   = _cnt('delegate')
    board_count = _cnt('board')
    presb_count = _cnt('presbyterial')
    act_count   = _cnt('activity_secretary')
    vis_count   = _cnt('visitor')
    mb_count    = _cnt('member')

    parts = [f'<b>Total de presentes: {total}</b>']
    if del_count:   parts.append(f'Delegados: {del_count}')
    if mb_count:    parts.append(f'Sócios: {mb_count}')
    if board_count: parts.append(f'Diretoria: {board_count}')
    if presb_count: parts.append(f'{presb_label}: {presb_count}')
    if act_count:   parts.append(f'Sec. Atividades: {act_count}')
    if vis_count:   parts.append(f'Visitantes: {vis_count}')
    story.append(Paragraph('  |  '.join(parts), ParagraphStyle('_sum',
        fontSize=8.5, textColor=BLACK, fontName='Helvetica', leading=13)))
    story.append(Spacer(1, 3 * mm))

    # Diretoria
    board_p = [a for a in present if a.get('attendee_type') == 'board']
    if board_p:
        story.append(_bold('Diretoria:'))
        for a in board_p:
            story.append(_item(f'• {a["name"]}'))
        story.append(Spacer(1, 2 * mm))

    # Presbyterial / Conselheiro
    presb_p = [a for a in present if a.get('attendee_type') == 'presbyterial']
    if presb_p:
        story.append(_bold(f'{presb_label}:'))
        for a in presb_p:
            story.append(_item(f'• {a["name"]}'))
        story.append(Spacer(1, 2 * mm))

    # Secretários de atividades
    act_p = [a for a in present if a.get('attendee_type') == 'activity_secretary']
    if act_p:
        story.append(_bold('Secretarias:'))
        for a in act_p:
            story.append(_item(f'• {a["name"]}'))
        story.append(Spacer(1, 2 * mm))

    # Delegados agrupados por local
    del_p = [a for a in present if a.get('attendee_type') == 'delegate']
    if del_p:
        story.append(_bold('Delegados:'))
        by_local = {}
        for a in del_p:
            key = a.get('local_name') or 'Outros'
            by_local.setdefault(key, []).append(a)
        for local_name, dels in sorted(by_local.items()):
            story.append(Paragraph(f'<b>{local_name}:</b>',
                ParagraphStyle('_loc', fontSize=8.5, textColor=BLACK,
                    fontName='Helvetica-Bold', leading=12, leftIndent=4 * mm)))
            for d in dels:
                story.append(_item(f'  • {d["name"]}', indent_mm=8))
        story.append(Spacer(1, 2 * mm))

    # Sócios
    mb_p = [a for a in present if a.get('attendee_type') == 'member']
    if mb_p:
        story.append(_bold('Sócios:'))
        for a in mb_p:
            story.append(_item(f'• {a["name"]}'))
        story.append(Spacer(1, 2 * mm))

    # Visitantes
    vis_p = [a for a in present if a.get('attendee_type') == 'visitor']
    if vis_p:
        story.append(_bold('Visitantes:'))
        for a in vis_p:
            obs = f' — {a["observation"]}' if a.get('observation') else ''
            story.append(_item(f'• {a["name"]}{obs}'))
        story.append(Spacer(1, 2 * mm))

    # Ausentes
    if absent:
        story.append(_bold('Ausentes:'))
        TYPE_LBL = {
            'board':              'Diretoria',
            'presbyterial':       presb_label,
            'activity_secretary': 'Secretário(a) de Atividades',
            'delegate':           'Delegado',
            'member':             'Sócio',
        }
        for a in absent:
            suffix = f' ({TYPE_LBL[a["attendee_type"]]})' \
                if a.get('attendee_type') in TYPE_LBL else ''
            story.append(_item(f'• {a["name"]}{suffix}'))
        story.append(Spacer(1, 3 * mm))

    # ── Seções de texto ──────────────────────────────────────
    SECTIONS = [
        ('section_devotional',   'ATO DEVOCIONAL'),
        ('section_agenda',       'PAUTA'),
        ('section_resolutions',  'RESOLUÇÕES'),
        ('section_observations', 'OBSERVAÇÕES'),
        ('section_closing',      'ENCERRAMENTO'),
    ]
    for field, title in SECTIONS:
        content = meeting_data.get(field)
        if not content or not content.strip():
            continue
        story.append(Spacer(1, 2 * mm))
        story.append(_sec_title(title))
        story.append(Spacer(1, 2 * mm))
        for line in content.split('\n'):
            if not line.strip():
                story.append(Spacer(1, 1 * mm))
                continue
            stripped = line.lstrip()
            indent_chars = len(line) - len(stripped)
            story.append(Paragraph(stripped, ParagraphStyle('_s',
                fontSize=8.5, textColor=BLACK, fontName='Helvetica',
                leading=12, leftIndent=indent_chars * 1.5 * mm, spaceAfter=1,
            )))

    # ── Linha de assinatura ──────────────────────────────────
    story.append(Spacer(1, 8 * mm))

    sec_full = meeting_data.get('meeting_secretary', '')
    sec_role = meeting_data.get('meeting_secretary_role', '1º Secretário(a)')
    if ' - ' in (sec_full or ''):
        sec_name_only = sec_full.split(' - ', 1)[1]
    else:
        sec_name_only = sec_full or ''

    sig_w = W / 2 - 10 * mm

    sig_block = Table([
        [HRFlowable(width=sig_w, thickness=1, color=BLACK)],
        [Paragraph(
            sec_name_only.upper() if sec_name_only else '________________________________',
            _ps(8.5, BLACK, bold=True, align=TA_CENTER)
        )],
        [Paragraph(
            sec_role or '1º Secretário(a)',
            _ps(8, GRAY_TXT, align=TA_CENTER)
        )],
    ], colWidths=[sig_w])
    sig_block.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
    ]))

    sig_outer = Table([[sig_block]], colWidths=[W])
    sig_outer.setStyle(TableStyle([
        ('ALIGN',  (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(sig_outer)

    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════
# RELATÓRIO FINANCEIRO
# ═══════════════════════════════════════════════════════════════

def generate_financial_report(
    org_data, period_data, months_data, board_data,
    logo_bytes=None, logo_content_type=None, theme_color='#1a2a6c',
    signature_data=None,
):
    buf = io.BytesIO()
    ML = MR = 14*mm
    W = A4[0] - ML - MR

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=14*mm, bottomMargin=14*mm)

    TC        = _tc(theme_color)
    year      = period_data.get('fiscal_year')
    org_name  = (org_data.get('name') or '').upper()
    is_fed    = org_data.get('organization_type') == 'federation'
    initial   = float(period_data.get('initial_balance') or 0)
    final_bal = float(period_data.get('final_balance') or 0)
    story     = []

    # ─── CABEÇALHO ───────────────────────────────────────────
    LOGO_W = 28
    HDR_H  = 35*mm
    logo_img = _logo(logo_bytes, LOGO_W, LOGO_W)

    # Conteúdo do bloco azul: 3 linhas em células separadas
    title_content = [
        [Paragraph('RELATÓRIO FINANCEIRO DA', _ps(9, WHITE, align=TA_CENTER))],
        [Paragraph(org_name,                  _ps(13, WHITE, bold=True, align=TA_CENTER))],
        [Paragraph(f'Ano {year}',             _ps(8, WHITE, align=TA_CENTER))],
    ]
    title_inner = Table(title_content, colWidths=[W - (LOGO_W*mm if logo_img else 0)])
    title_inner.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), TC),
        ('TOPPADDING',    (0,0),(-1,-1), 2),
        ('BOTTOMPADDING', (0,0),(-1,-1), 2),
        ('LEFTPADDING',   (0,0),(-1,-1), 6),
        ('RIGHTPADDING',  (0,0),(-1,-1), 6),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
    ]))

    if logo_img:
        hdr_row = [[logo_img, title_inner]]
        hdr_cw  = [LOGO_W*mm, W - LOGO_W*mm]
    else:
        hdr_row = [[title_inner]]
        hdr_cw  = [W]

    hdr = Table(hdr_row, colWidths=hdr_cw, rowHeights=[HDR_H])
    hdr.setStyle(TableStyle([
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 0),
        ('BOTTOMPADDING', (0,0),(-1,-1), 0),
        ('LEFTPADDING',   (0,0),(-1,-1), 0),
        ('RIGHTPADDING',  (0,0),(-1,-1), 0),
        ('BACKGROUND',    (1 if logo_img else 0, 0), (-1, 0), TC),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 6*mm))

    # ─── IDENTIFICAÇÃO ──────────────────────────────────────
    story.append(_section_bar('INFORMAÇÕES GERAIS', W, TC))
    story.append(Spacer(1, 1*mm))
    story.append(_section_bar('IDENTIFICAÇÃO DA ORGANIZAÇÃO', W, TC))

    presidente = next((b for b in board_data if b.get('role')=='presidente'), None)
    tesoureiro  = next((b for b in board_data if b.get('role')=='tesoureiro'),  None)

    LW = 48*mm
    VW = W - LW

    def _irow(label, value, shade=False):
        return [
            Paragraph(label.upper(), _ps(7, GRAY_TXT, align=TA_RIGHT)),
            Paragraph(str(value or '—'), _ps(7.5, BLACK)),
        ], shade

    org_label = 'FEDERAÇÃO' if is_fed else (org_data.get('society_type') or 'UMP')

    id_defs = [
        _irow(org_label, (org_data.get('name') or '').upper()),
        _irow('PRESBITÉRIO', (org_data.get('presbytery_name') or '').upper(), True),
    ]
    if not is_fed:
        id_defs.append(_irow('IGREJA', (org_data.get('church_name') or '').upper()))
        id_defs.append(_irow('PASTOR', (org_data.get('pastor_name') or '—').upper(), True))

    id_defs.append(_irow('ANO VIGENTE', str(year), shade=len(id_defs)%2==0))
    id_defs.append(_irow('PRESIDENTE',
        (presidente.get('member_name') or '—').upper() if presidente else '—',
        shade=len(id_defs)%2==1))
    id_defs.append(_irow('TESOUREIRO(A) RESPONSÁVEL',
        (tesoureiro.get('member_name') or '—').upper() if tesoureiro else '—',
        shade=len(id_defs)%2==0))

    id_data   = [row for row, _ in id_defs]
    id_styles = [
        ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
    ]
    for i, (_, shade) in enumerate(id_defs):
        if shade:
            id_styles.append(('BACKGROUND', (0,i),(-1,i), GRAY_ROW))

    id_t = Table(id_data, colWidths=[LW, VW])
    id_t.setStyle(TableStyle(id_styles))
    story.append(id_t)
    story.append(Spacer(1, 5*mm))

    # ─── TABELA FINANCEIRA ──────────────────────────────────
    total_in  = sum(float(m.get('total_in',  0)) for m in months_data)
    total_out = sum(float(m.get('total_out', 0)) for m in months_data)
    aci_in    = sum(sum(float(t['amount']) for t in m.get('transactions',[])
                        if t['transaction_type']=='aci_recebida') for m in months_data)
    aci_out   = sum(sum(float(t['amount']) for t in m.get('transactions',[])
                        if t['transaction_type']=='aci_enviada') for m in months_data)
    outras_rec = total_in  - aci_in
    outras_des = total_out - aci_out
    story.append(_section_bar(f'INFORMAÇÕES FINANCEIRAS {year}', W, TC))

    HW  = W / 2
    LLW = 38*mm
    RRW = HW - LLW

    def _fhdr(txt):
        return Paragraph(txt, _ps(8, WHITE, bold=True, align=TA_CENTER))
    def _fl(txt, bold=False):
        return Paragraph(txt, _ps(7.5, BLACK, bold=bold))
    def _fr(txt, bold=False, color=BLACK):
        return Paragraph(txt, _ps(7.5, color, bold=bold, align=TA_RIGHT))

    fin_data = [
        [Paragraph(f'SALDO DO ANO ANTERIOR {year-1}', _ps(8, WHITE, bold=True)),
         Paragraph(_fc(initial), _ps(8, WHITE, bold=True, align=TA_RIGHT)),
         Paragraph('', _ps(8, WHITE)),
         Paragraph('', _ps(8, WHITE))],

        [_fhdr(f'RECEITAS ({year})'), _fhdr(''),
         _fhdr(f'DESPESAS ({year})'), _fhdr('')],

        [_fl('ACI Recebida'),        _fr(_fc(aci_in)),
         _fl('ACI Enviada'),         _fr(_fc(aci_out))],

        [_fl('Outras Receitas (+)'), _fr(_fc(outras_rec)),
         _fl('Outras Despesas (−)'), _fr(_fc(outras_des))],

        [_fl('TOTAL DA RECEITA ANUAL', bold=True), _fr(_fc(total_in), bold=True),
         _fl('TOTAL DA DESPESA ANUAL', bold=True), _fr(_fc(total_out), bold=True)],

        [_fl('TOTAL GERAL (SALDO + RECEITAS)', bold=True),
         _fr(_fc(initial + total_in), bold=True),
         _fl(f'SALDO FINAL PARA {year+1}', bold=True),
         _fr(_fc(final_bal), bold=True)],
    ]

    fin_t = Table(fin_data, colWidths=[LLW, RRW, LLW, RRW])
    fin_t.setStyle(TableStyle([
        ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 4),
        ('BOTTOMPADDING', (0,0),(-1,-1), 4),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
        # Linha 0: azul esquerda, cinza direita
        ('BACKGROUND',    (0,0),(1,0), TC),
        ('BACKGROUND',    (2,0),(3,0), GRAY_ROW),
        # Linha 1: cabeçalhos
        ('BACKGROUND',    (0,1),(1,1), TC),
        ('SPAN',          (0,1),(1,1)),
        ('BACKGROUND',    (2,1),(3,1), TC),
        ('SPAN',          (2,1),(3,1)),
        # Linhas alternadas
        ('BACKGROUND',    (0,2),(-1,2), GRAY_ROW),
        ('BACKGROUND',    (0,4),(-1,4), GRAY_ROW),
        ('BACKGROUND',    (0,5),(-1,5), GRAY_ROW),
    ]))
    story.append(fin_t)
    story.append(Spacer(1, 3*mm))

    # ─── OBSERVAÇÕES ────────────────────────────────────────
    obs_text = period_data.get('observations') or ''
    obs_t = Table([
        [Paragraph('OBSERVAÇÕES:', _ps(7, GRAY_TXT, bold=True))],
        [Paragraph(obs_text, _ps(8, BLACK)) if obs_text else Spacer(1, 8*mm)],
    ], colWidths=[W], rowHeights=[5*mm, 14*mm])
    obs_t.setStyle(TableStyle([
        ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
        ('BACKGROUND',    (0,0),(-1,-1), YELLOW_BG),
        ('VALIGN',        (0,0),(-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
    ]))
    story.append(obs_t)
    story.append(Spacer(1, 3*mm))

    # ─── ASSINATURAS ────────────────────────────────────────
    if signature_data:
        story.append(Spacer(1, 2*mm))

        QR_SIZE = 20*mm
        qr_img = None
        if signature_data.get('qr_bytes'):
            try:
                qr_img = Image(io.BytesIO(signature_data['qr_bytes']),
                               width=QR_SIZE, height=QR_SIZE)
            except Exception:
                pass

        code     = signature_data.get('validation_code', '')
        hash_val = signature_data.get('data_hash', '')
        req_name = signature_data.get('requested_by', '')
        app_name = signature_data.get('approved_by', '')
        req_role = signature_data.get('req_role', 'Tesoureiro(a)')
        app_role = signature_data.get('app_role', 'Presidente')

        PAD   = 5*mm
        INNER = W - 2*PAD
        TEXT_W = INNER - (QR_SIZE + 4*mm if qr_img else 0)

        text_items = [
            Paragraph('<b>DOCUMENTO ASSINADO DIGITALMENTE</b>', _ps(8, TC, bold=True)),
            Spacer(1, 1*mm),
            Paragraph(f'Código: <b>{code}</b>', _ps(7.5, BLACK)),
            Paragraph(f'Hash: {hash_val[:38]}...', _ps(6, GRAY_TXT)),
            Spacer(1, 1*mm),
            Paragraph(
                f'{req_role}: <b>{req_name}</b>  |  {app_role}: <b>{app_name}</b>',
                _ps(7, BLACK)
            ),
            Paragraph(
                f'Aprovado em: <b>{signature_data.get("approved_at","")}</b>',
                _ps(7, BLACK)
            ),
            Spacer(1, 1*mm),
            Paragraph('Valide em: umpgestao.netlify.app/validar.html', _ps(6.5, GRAY_TXT)),
        ]

        text_t = Table([[item] for item in text_items], colWidths=[TEXT_W])
        text_t.setStyle(TableStyle([
            ('TOPPADDING',    (0,0),(-1,-1), 0),
            ('BOTTOMPADDING', (0,0),(-1,-1), 0),
            ('LEFTPADDING',   (0,0),(-1,-1), 0),
            ('RIGHTPADDING',  (0,0),(-1,-1), 0),
        ]))

        if qr_img:
            qr_t = Table([[qr_img]], colWidths=[QR_SIZE], rowHeights=[QR_SIZE])
            qr_t.setStyle(TableStyle([
                ('TOPPADDING',    (0,0),(-1,-1), 0),
                ('BOTTOMPADDING', (0,0),(-1,-1), 0),
                ('LEFTPADDING',   (0,0),(-1,-1), 0),
                ('RIGHTPADDING',  (0,0),(-1,-1), 0),
            ]))
            inner_t = Table([[text_t, Spacer(4*mm, 1), qr_t]],
                            colWidths=[TEXT_W, 4*mm, QR_SIZE])
        else:
            inner_t = Table([[text_t]], colWidths=[INNER])

        inner_t.setStyle(TableStyle([
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('LEFTPADDING',   (0,0),(-1,-1), 0),
            ('RIGHTPADDING',  (0,0),(-1,-1), 0),
            ('TOPPADDING',    (0,0),(-1,-1), 0),
            ('BOTTOMPADDING', (0,0),(-1,-1), 0),
        ]))

        card = Table([[inner_t]], colWidths=[W])
        card.setStyle(TableStyle([
            ('BOX',           (0,0),(-1,-1), 1.5, TC),
            ('BACKGROUND',    (0,0),(-1,-1), colors.HexColor('#f8fafc')),
            ('TOPPADDING',    (0,0),(-1,-1), PAD * 0.6),
            ('BOTTOMPADDING', (0,0),(-1,-1), PAD * 0.6),
            ('LEFTPADDING',   (0,0),(-1,-1), PAD),
            ('RIGHTPADDING',  (0,0),(-1,-1), PAD),
        ]))
        story.append(card)
        story.append(Spacer(1, 3*mm))

        # Linhas de assinatura digital com cargo
        SIG_W2 = (W - 20*mm) / 2

        def _sig_digital(role_label, name):
            return Table([
                [HRFlowable(width=SIG_W2, thickness=1, color=BLACK)],
                [Paragraph(role_label,   _ps(7, GRAY_TXT, align=TA_CENTER))],
                [Paragraph(name.upper(), _ps(9, BLACK, bold=True, align=TA_CENTER))],
                [Paragraph(org_name,     _ps(7.5, BLACK, align=TA_CENTER))],
            ], colWidths=[SIG_W2])

        sig_t2 = Table([[
            _sig_digital(req_role, req_name),
            Spacer(20*mm, 1),
            _sig_digital(app_role, app_name),
        ]], colWidths=[SIG_W2, 20*mm, SIG_W2])
        sig_t2.setStyle(TableStyle([('VALIGN', (0,0),(-1,-1), 'TOP')]))
        story.append(sig_t2)
        story.append(Spacer(1, 4*mm))
    else:
        # Bloco de assinatura manual
        SIG_W = (W - 20*mm) / 2
        pres_name = (presidente.get('member_name') or '').upper() if presidente else ''
        tes_name  = (tesoureiro.get('member_name')  or '').upper() if tesoureiro else ''

        def _sig(name, role):
            return Table([
                [HRFlowable(width=SIG_W, thickness=1, color=BLACK)],
                [Paragraph(name, _ps(9, BLACK, bold=True, align=TA_CENTER))],
                [Paragraph(role, _ps(8, BLACK, align=TA_CENTER))],
                [Paragraph(org_name, _ps(8, BLACK, bold=True, align=TA_CENTER))],
            ], colWidths=[SIG_W])

        sig_t = Table([
            [_sig(pres_name, 'Presidente da'),
             Spacer(20*mm, 1),
             _sig(tes_name, 'Tesoureiro(a) da')]
        ], colWidths=[SIG_W, 20*mm, SIG_W])
        sig_t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
        story.append(sig_t)
        story.append(Spacer(1, 6*mm))

    presby = (org_data.get('presbytery_name') or '').upper()
    ft_txt = f'{org_name} — {presby}' if presby else org_name
    ft = Table([[Paragraph(ft_txt, _ps(7.5, WHITE, bold=True, align=TA_CENTER))]],
               colWidths=[W], rowHeights=[7*mm])
    ft.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,-1), TC),
        ('VALIGN',     (0,0),(-1,-1), 'MIDDLE'),
    ]))
    story.append(ft)

    # ─── PÁGINAS DOS MESES ──────────────────────────────────
    # Numeração global para coincidir com relatório de comprovantes
    global_num = {}
    n = 0
    for m in months_data:
        for t in m.get('transactions', []):
            n += 1
            global_num[str(t.get('id',''))] = n

    for month in months_data:
        story.append(PageBreak())

        # Cabeçalho do mês
        month_name = month['month_label'].upper()
        title_w_m  = W - (22*mm if logo_img else 0)

        title_m = Table([
            [Paragraph(org_name,                             _ps(7,  WHITE, align=TA_CENTER))],
            [Paragraph(f'{month_name} {year}',               _ps(12, WHITE, bold=True, align=TA_CENTER))],
            [Paragraph('Relatório Financeiro Mensal',         _ps(6.5,WHITE, align=TA_CENTER))],
        ], colWidths=[title_w_m])
        title_m.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(-1,-1), TC),
            ('TOPPADDING',    (0,0),(-1,-1), 2),
            ('BOTTOMPADDING', (0,0),(-1,-1), 2),
            ('LEFTPADDING',   (0,0),(-1,-1), 6),
            ('RIGHTPADDING',  (0,0),(-1,-1), 6),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ]))

        m_logo = _logo(logo_bytes, 22, 22) if logo_img else None
        if m_logo:
            mhdr_row = [[m_logo, title_m]]
            mhdr_cw  = [22*mm, title_w_m]
        else:
            mhdr_row = [[title_m]]
            mhdr_cw  = [W]

        mhdr = Table(mhdr_row, colWidths=mhdr_cw, rowHeights=[28*mm])
        mhdr.setStyle(TableStyle([
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('TOPPADDING',    (0,0),(-1,-1), 0),
            ('BOTTOMPADDING', (0,0),(-1,-1), 0),
            ('LEFTPADDING',   (0,0),(-1,-1), 0),
            ('RIGHTPADDING',  (0,0),(-1,-1), 0),
            ('BACKGROUND',    (1 if m_logo else 0, 0),(-1,0), TC),
        ]))
        story.append(mhdr)
        story.append(Spacer(1, 4*mm))

        # Resumo do mês — 4 colunas simples
        QW = W / 4
        summary_data = [[
            Paragraph('SALDO ANTERIOR', _ps(6.5, GRAY_TXT, align=TA_CENTER)),
            Paragraph('ENTRADAS',       _ps(6.5, GRAY_TXT, align=TA_CENTER)),
            Paragraph('SAÍDAS',         _ps(6.5, GRAY_TXT, align=TA_CENTER)),
            Paragraph('SALDO DO MÊS',   _ps(6.5, GRAY_TXT, align=TA_CENTER)),
        ], [
            Paragraph(_fc(month['opening_balance']), _ps(8.5, TC,    bold=True, align=TA_CENTER)),
            Paragraph(_fc(month['total_in']),        _ps(8.5, GREEN, bold=True, align=TA_CENTER)),
            Paragraph(_fc(month['total_out']),       _ps(8.5, RED_C, bold=True, align=TA_CENTER)),
            Paragraph(_fc(month['closing_balance']), _ps(8.5, TC,    bold=True, align=TA_CENTER)),
        ]]
        sum_t = Table(summary_data, colWidths=[QW, QW, QW, QW])
        sum_t.setStyle(TableStyle([
            ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
            ('BACKGROUND',    (0,0),(-1,-1), GRAY_ROW),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('TOPPADDING',    (0,0),(-1,-1), 5),
            ('BOTTOMPADDING', (0,0),(-1,-1), 5),
            ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
            ('SPAN',          (0,0),(0,0)),
        ]))
        story.append(sum_t)
        story.append(Spacer(1, 4*mm))

        txs = month.get('transactions', [])
        if not txs:
            story.append(Paragraph(
                'Nenhum lançamento registrado neste mês.',
                _ps(9, GRAY_TXT, align=TA_CENTER)
            ))
        else:
            NUM_W = 10*mm
            DAT_W = 20*mm
            TYP_W = 32*mm
            VAL_W = 28*mm
            CMP_W = 24*mm
            DSC_W = W - NUM_W - DAT_W - TYP_W - VAL_W - CMP_W

            tx_rows = [[
                Paragraph('Nº',          _ps(8, WHITE, bold=True, align=TA_CENTER)),
                Paragraph('Data',        _ps(8, WHITE, bold=True, align=TA_CENTER)),
                Paragraph('Tipo',        _ps(8, WHITE, bold=True)),
                Paragraph('Descrição',   _ps(8, WHITE, bold=True)),
                Paragraph('Valor',       _ps(8, WHITE, bold=True, align=TA_RIGHT)),
                Paragraph('Comprov.',    _ps(8, WHITE, bold=True, align=TA_CENTER)),
            ]]
            for t in txs:
                nature = 'in' if t['transaction_type'] in INCOME else 'out'
                vc     = GREEN if nature == 'in' else RED_C
                sign   = '+ ' if nature == 'in' else '– '
                num    = global_num.get(str(t.get('id','')), '—')
                has_r  = bool(t.get('receipt_url'))
                tx_rows.append([
                    Paragraph(str(num), _ps(7.5, BLACK, align=TA_CENTER)),
                    Paragraph(_fd(t.get('transaction_date','')), _ps(7.5, BLACK, align=TA_CENTER)),
                    Paragraph(TYPE_LABELS.get(t['transaction_type'],''), _ps(7.5, BLACK)),
                    Paragraph((t.get('description') or '')[:55], _ps(7.5, BLACK)),
                    Paragraph(sign + _fc(t['amount']), _ps(7.5, vc, bold=True, align=TA_RIGHT)),
                    Paragraph('✓' if has_r else '—',
                               _ps(7.5, GREEN if has_r else GRAY_TXT, align=TA_CENTER)),
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

        story.append(Spacer(1, 4*mm))
        story.append(HRFlowable(width=W, thickness=0.5, color=GRAY_LINE))
        story.append(Paragraph(
            f'{org_data.get("name","")} · Relatório Financeiro {year}',
            _ps(6.5, GRAY_TXT, align=TA_CENTER)
        ))

    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════
# RELATÓRIO DE COMPROVANTES
# ═══════════════════════════════════════════════════════════════

def generate_receipts_report(
    org_data, period_data, months_data,
    b2_client, bucket_name, theme_color='#1a2a6c',
    board_data=None, logo_bytes=None,
):
    buf = io.BytesIO()
    ML = MR = 14*mm
    W = A4[0] - ML - MR

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=14*mm, bottomMargin=14*mm)

    TC   = _tc(theme_color)
    year = period_data.get('fiscal_year')
    org_name = (org_data.get('name') or '').upper()
    story = []

    # ── Capa elaborada ──
    # Cabeçalho com logo + bloco colorido (mesmo padrão do financeiro)
    logo_img_capa = _logo(logo_bytes, 28, 28) if logo_bytes else None
    title_w_capa = W - (28*mm if logo_img_capa else 0)

    title_capa = Table([
        [Paragraph('RELATÓRIO DE COMPROVANTES', _ps(9, WHITE, align=TA_CENTER))],
        [Paragraph(org_name,                    _ps(13, WHITE, bold=True, align=TA_CENTER))],
        [Paragraph(f'Ano {year}',               _ps(8, WHITE, align=TA_CENTER))],
    ], colWidths=[title_w_capa])
    title_capa.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), TC),
        ('TOPPADDING',    (0,0),(-1,-1), 2),
        ('BOTTOMPADDING', (0,0),(-1,-1), 2),
        ('LEFTPADDING',   (0,0),(-1,-1), 6),
        ('RIGHTPADDING',  (0,0),(-1,-1), 6),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
    ]))

    if logo_img_capa:
        hdr_capa_row = [[logo_img_capa, title_capa]]
        hdr_capa_cw  = [28*mm, title_w_capa]
    else:
        hdr_capa_row = [[title_capa]]
        hdr_capa_cw  = [W]

    hdr_capa = Table(hdr_capa_row, colWidths=hdr_capa_cw, rowHeights=[35*mm])
    hdr_capa.setStyle(TableStyle([
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 0),
        ('BOTTOMPADDING', (0,0),(-1,-1), 0),
        ('LEFTPADDING',   (0,0),(-1,-1), 0),
        ('RIGHTPADDING',  (0,0),(-1,-1), 0),
        ('BACKGROUND',    (1 if logo_img_capa else 0, 0),(-1,0), TC),
    ]))
    story.append(hdr_capa)
    story.append(Spacer(1, 6*mm))

    # Faixa informativa
    story.append(_section_bar('INFORMAÇÕES DO PERÍODO', W, TC))
    story.append(Spacer(1, 1*mm))

    # Tabela com dados do período
    is_fed_rec = org_data.get('organization_type') == 'federation'
    org_label_rec = 'FEDERAÇÃO' if is_fed_rec else (org_data.get('society_type') or 'UMP')

    # Conta total de lançamentos e comprovantes
    total_txs = sum(len(m.get('transactions', [])) for m in months_data)
    total_receipts = sum(
        sum(1 for t in m.get('transactions', []) if t.get('receipt_url'))
        for m in months_data
    )
    total_in_rec  = sum(float(m.get('total_in',  0)) for m in months_data)
    total_out_rec = sum(float(m.get('total_out', 0)) for m in months_data)

    presidente_rec = next((b for b in board_data if b.get('role') == 'presidente'), None) if board_data else None
    tesoureiro_rec  = next((b for b in board_data if b.get('role') == 'tesoureiro'),  None) if board_data else None

    LWC = 48*mm
    VWC = W - LWC
    info_capa_data = [
        [Paragraph(org_label_rec.upper(), _ps(7, GRAY_TXT, align=TA_RIGHT)),
         Paragraph((org_data.get('name') or '').upper(), _ps(7.5, BLACK))],
        [Paragraph('PRESBITÉRIO', _ps(7, GRAY_TXT, align=TA_RIGHT)),
         Paragraph((org_data.get('presbytery_name') or '—').upper(), _ps(7.5, BLACK))],
        [Paragraph('ANO DO PERÍODO', _ps(7, GRAY_TXT, align=TA_RIGHT)),
         Paragraph(str(year), _ps(7.5, BLACK))],
        [Paragraph('TOTAL DE LANÇAMENTOS', _ps(7, GRAY_TXT, align=TA_RIGHT)),
         Paragraph(str(total_txs), _ps(7.5, BLACK))],
        [Paragraph('LANÇAMENTOS COM COMPROVANTE', _ps(7, GRAY_TXT, align=TA_RIGHT)),
         Paragraph(f'{total_receipts} de {total_txs}', _ps(7.5, BLACK))],
        [Paragraph('TOTAL DE RECEITAS', _ps(7, GRAY_TXT, align=TA_RIGHT)),
         Paragraph(_fc(total_in_rec), _ps(7.5, GREEN, bold=True))],
        [Paragraph('TOTAL DE DESPESAS', _ps(7, GRAY_TXT, align=TA_RIGHT)),
         Paragraph(_fc(total_out_rec), _ps(7.5, RED_C, bold=True))],
        [Paragraph('DATA DE GERAÇÃO', _ps(7, GRAY_TXT, align=TA_RIGHT)),
         Paragraph(datetime.date.today().strftime('%d/%m/%Y'), _ps(7.5, BLACK))],
    ]
    info_capa_styles = [
        ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
    ]
    for i in [1, 3, 5, 7]:
        if i < len(info_capa_data):
            info_capa_styles.append(('BACKGROUND', (0,i),(-1,i), GRAY_ROW))

    info_capa_t = Table(info_capa_data, colWidths=[LWC, VWC])
    info_capa_t.setStyle(TableStyle(info_capa_styles))
    story.append(info_capa_t)
    story.append(Spacer(1, 5*mm))

    # Responsáveis — apenas nomes destacados, sem linha de assinatura
    if presidente_rec or tesoureiro_rec:
        story.append(_section_bar('RESPONSÁVEIS', W, TC))
        story.append(Spacer(1, 1*mm))

        pres_name_rec = (presidente_rec.get('member_name') or '').upper() if presidente_rec else '—'
        tes_name_rec  = (tesoureiro_rec.get('member_name')  or '').upper() if tesoureiro_rec  else '—'

        resp_data = [
            [Paragraph('PRESIDENTE', _ps(7, GRAY_TXT, align=TA_RIGHT)),
             Paragraph(pres_name_rec, _ps(8, BLACK, bold=True)),
             Paragraph('TESOUREIRO(A)', _ps(7, GRAY_TXT, align=TA_RIGHT)),
             Paragraph(tes_name_rec, _ps(8, BLACK, bold=True))],
        ]
        HWR = W / 2
        LWR = 32*mm
        VWR = HWR - LWR
        resp_t = Table(resp_data, colWidths=[LWR, VWR, LWR, VWR])
        resp_t.setStyle(TableStyle([
            ('GRID',          (0,0),(-1,-1), 0.5, GRAY_LINE),
            ('BACKGROUND',    (0,0),(-1,-1), GRAY_ROW),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('TOPPADDING',    (0,0),(-1,-1), 5),
            ('BOTTOMPADDING', (0,0),(-1,-1), 5),
            ('LEFTPADDING',   (0,0),(-1,-1), 4),
            ('RIGHTPADDING',  (0,0),(-1,-1), 4),
        ]))
        story.append(resp_t)
        story.append(Spacer(1, 5*mm))

    # Rodapé da capa
    presby_rec = (org_data.get('presbytery_name') or '').upper()
    ft_txt_rec = f'{org_name} — {presby_rec}' if presby_rec else org_name
    ft_rec = Table([[Paragraph(ft_txt_rec, _ps(7.5, WHITE, bold=True, align=TA_CENTER))]],
                   colWidths=[W], rowHeights=[7*mm])
    ft_rec.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,-1), TC),
        ('VALIGN',     (0,0),(-1,-1), 'MIDDLE'),
    ]))
    story.append(ft_rec)
    story.append(PageBreak())

    receipt_num = 0
    for month in months_data:
        for t in month.get('transactions', []):
            receipt_num += 1
            has_receipt = bool(t.get('receipt_url'))

            # Cabeçalho
            hdr = Table([[
                Paragraph(f'COMPROVANTE Nº {receipt_num:03d}', _ps(9, WHITE, bold=True)),
                Paragraph(f'{month["month_label"]} {year}',    _ps(7.5, WHITE, align=TA_RIGHT)),
            ]], colWidths=[W * 0.6, W * 0.4])
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

            # Dados
            nature = 'in' if t['transaction_type'] in INCOME else 'out'
            vc     = GREEN if nature == 'in' else RED_C
            sign   = '+ ' if nature == 'in' else '– '
            LW2 = 28*mm
            HW2 = W / 2
            VW2 = HW2 - LW2

            info_t = Table([
                [Paragraph('DATA',      _ps(7, GRAY_TXT, align=TA_RIGHT)),
                 Paragraph(_fd(t.get('transaction_date','')), _ps(8, BLACK)),
                 Paragraph('TIPO',      _ps(7, GRAY_TXT, align=TA_RIGHT)),
                 Paragraph(TYPE_LABELS.get(t['transaction_type'],''), _ps(8, BLACK))],
                [Paragraph('DESCRIÇÃO', _ps(7, GRAY_TXT, align=TA_RIGHT)),
                 Paragraph(t.get('description',''), _ps(8, BLACK)),
                 Paragraph('VALOR',     _ps(7, GRAY_TXT, align=TA_RIGHT)),
                 Paragraph(sign + _fc(t['amount']), _ps(9, vc, bold=True))],
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

            # Imagem
            if has_receipt:
                img_bytes, ct = _download_b2(b2_client, bucket_name, t['receipt_url'])
                is_pdf = (ct == 'application/pdf' or
                          str(t.get('receipt_url','')).lower().endswith('.pdf'))
                if img_bytes and not is_pdf:
                    try:
                        from PIL import Image as PILImg
                        pil = PILImg.open(io.BytesIO(img_bytes))
                        ow, oh = pil.size
                        MAX_W = W
                        MAX_H = 190*mm
                        ratio = min(MAX_W/(ow*0.352778), MAX_H/(oh*0.352778))
                        iw = ow * 0.352778 * ratio
                        ih = oh * 0.352778 * ratio
                        rl_img = Image(io.BytesIO(img_bytes), width=iw, height=ih)
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
                        story.append(Paragraph('Erro ao carregar imagem.',
                                               _ps(8, RED_C, align=TA_CENTER)))
                elif is_pdf:
                    story.append(Paragraph(
                        'Comprovante em formato PDF — arquivo original mantido no armazenamento.',
                        _ps(9, GRAY_TXT, align=TA_CENTER)))
                else:
                    story.append(Paragraph(
                        'Comprovante não disponível.',
                        _ps(9, GRAY_TXT, align=TA_CENTER)))
            else:
                story.append(Paragraph(
                    'Nenhum comprovante anexado a este lançamento.',
                    _ps(9, GRAY_TXT, align=TA_CENTER)))

            story.append(Spacer(1, 3*mm))
            story.append(HRFlowable(width=W, thickness=0.5, color=GRAY_LINE))
            story.append(Paragraph(
                f'Comprovante {receipt_num:03d} · {org_data.get("name","")} · {year}',
                _ps(6.5, GRAY_TXT, align=TA_CENTER)
            ))
            story.append(PageBreak())

    if receipt_num == 0:
        story.append(Paragraph(
            'Nenhum comprovante encontrado para este período.',
            _ps(11, GRAY_TXT, align=TA_CENTER)
        ))

    doc.build(story)
    return buf.getvalue()