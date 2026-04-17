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
# RELATÓRIO DE ATIVIDADES
# ═══════════════════════════════════════════════════════════════

def generate_activity_report(
    org_data: dict,
    fiscal_year: int,
    board_data: list,
    act_secs_data: list,
    activities: list,
    report: dict,
    logo_bytes: bytes = None,
    ipb_logo_bytes: bytes = None,
) -> bytes:
    """Gera o Relatório de Atividades no modelo oficial."""
    import datetime as _dt

    buf = io.BytesIO()
    ML = MR = 15 * mm
    W = A4[0] - ML - MR

    # Cabeçalho e rodapé em todas as páginas
    def _make_header_footer(canvas_obj, doc_obj):
        canvas_obj.saveState()
        W_page = A4[0]
        ML_page = ML
        W_content = W_page - ML - MR

        # ── Cabeçalho (a partir da 2ª página)
        if doc_obj.page > 1:
            canvas_obj.setStrokeColor(colors.HexColor(org_data.get('theme_color','#1a2a6c')))
            canvas_obj.setLineWidth(0.5)

            # Logo IPB
            if ipb_logo_bytes:
                try:
                    from reportlab.lib.utils import ImageReader
                    ipb_reader = ImageReader(io.BytesIO(ipb_logo_bytes))
                    canvas_obj.drawImage(ipb_reader, ML_page, A4[1]-13*mm,
                                         width=9*mm, height=9*mm,
                                         preserveAspectRatio=True, mask='auto')
                except:
                    pass

            # Logo da org
            if logo_bytes:
                try:
                    from reportlab.lib.utils import ImageReader
                    org_reader = ImageReader(io.BytesIO(logo_bytes))
                    canvas_obj.drawImage(org_reader, W_page-MR-9*mm, A4[1]-13*mm,
                                         width=9*mm, height=9*mm,
                                         preserveAspectRatio=True, mask='auto')
                except:
                    pass

            # Título central
            canvas_obj.setFont('Helvetica-Bold', 8)
            canvas_obj.setFillColor(colors.black)
            canvas_obj.drawCentredString(
                W_page/2, A4[1]-9*mm,
                'RELATÓRIO DE ATIVIDADES'
            )
            canvas_obj.setFont('Helvetica', 7)
            canvas_obj.setFillColor(colors.HexColor('#64748b'))
            canvas_obj.drawCentredString(
                W_page/2, A4[1]-13*mm,
                f'Gestão {fiscal_year}  ·  {org_data.get("name","")}'
            )

            # Linha separadora do cabeçalho
            canvas_obj.setStrokeColor(colors.HexColor('#e2e8f0'))
            canvas_obj.line(ML_page, A4[1]-15*mm, W_page-MR, A4[1]-15*mm)

        # ── Rodapé em todas as páginas ──
        canvas_obj.setStrokeColor(colors.HexColor('#e2e8f0'))
        canvas_obj.line(ML_page, 12*mm, W_page-MR, 12*mm)

        # Lema/texto à esquerda no rodapé (configurável)
        canvas_obj.setFont('Helvetica', 6.5)
        canvas_obj.setFillColor(colors.HexColor('#94a3b8'))
        footer_text = org_data.get('footer_text') or \
            'ALEGRES NA ESPERANÇA – FORTES NA FÉ – DEDICADOS NO AMOR – UNIDOS NO TRABALHO'
        canvas_obj.drawCentredString(W_page/2, 8*mm, footer_text)

        # Número da página à direita
        canvas_obj.setFont('Helvetica', 7)
        canvas_obj.setFillColor(colors.HexColor('#94a3b8'))
        canvas_obj.drawRightString(W_page-MR, 8*mm, f'Página {doc_obj.page}')

        canvas_obj.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR,
        topMargin=20*mm,
        bottomMargin=18*mm
    )

    TC = _tc(org_data.get('theme_color', '#1a2a6c'))
    story = []

    MONTH_NAMES_PT = [
        'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
    ]

    def _p(txt, size=10, color=BLACK, bold=False, align=TA_LEFT,
           leading=None, indent=0, space_before=0, space_after=2):
        return Paragraph(str(txt or ''), ParagraphStyle('_',
            fontSize=size, textColor=color,
            fontName='Helvetica-Bold' if bold else 'Helvetica',
            alignment=align,
            leading=leading or size * 1.5,
            leftIndent=indent * mm,
            spaceBefore=space_before, spaceAfter=space_after,
        ))

    def section_hdr(txt):
        t = Table([[_p(txt, 9, WHITE, bold=True)]], colWidths=[W])
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), TC),
            ('TOPPADDING',    (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ]))
        return t

    def section_bar_num(num, title):
        t = Table([[_p(f'{num}. {title}', 10, WHITE, bold=True, align=TA_RIGHT)]], colWidths=[W])
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), TC),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ]))
        return t

    def render_text(text_content):
        if not text_content:
            return
        for para in text_content.split('\n'):
            stripped = para.strip()
            if not stripped:
                story.append(Spacer(1, 2 * mm))
                continue
            story.append(Paragraph(stripped, ParagraphStyle('body',
                fontSize=10, textColor=BLACK, fontName='Helvetica',
                alignment=4, leading=16, firstLineIndent=10 * mm,
                spaceAfter=2, spaceBefore=0,
            )))

    # ── CABEÇALHO ────────────────────────────────────────────
    logo_cell = _logo(logo_bytes, 22, 22) or Paragraph('', _ps())
    ipb_cell  = _logo(ipb_logo_bytes, 22, 22) or Paragraph('', _ps())

    title_w = W - 44 * mm
    org_name   = org_data.get('name', '')
    presbytery = org_data.get('presbytery_name', '')
    synodal    = org_data.get('synodal_name', '')

    title_block = Table([
        [_p('RELATÓRIO DE ATIVIDADES', 14, BLACK, bold=True, align=TA_CENTER)],
        [_p(f'Gestão {fiscal_year}', 9, GRAY_TXT, align=TA_CENTER)],
        [_p(org_name, 9, GRAY_TXT, align=TA_CENTER)],
        [_p(presbytery, 9, GRAY_TXT, align=TA_CENTER)],
        [_p(synodal, 9, GRAY_TXT, align=TA_CENTER) if synodal else Spacer(1, 1)],
    ], colWidths=[title_w])
    title_block.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    hdr = Table([[logo_cell, title_block, ipb_cell]], colWidths=[22 * mm, title_w, 22 * mm])
    hdr.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
        ('TOPPADDING',    (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width=W, thickness=0.5, color=GRAY_LINE))
    story.append(Spacer(1, 4 * mm))

    # ── DADOS GERAIS ─────────────────────────────────────────
    story.append(section_hdr('DADOS GERAIS'))
    LW = 45 * mm
    geral_data = [
        [_p('Nome', 9, GRAY_TXT, align=TA_RIGHT),        _p(org_name, 9, BLACK)],
        [_p('Presbitério', 9, GRAY_TXT, align=TA_RIGHT),  _p(presbytery, 9, BLACK)],
        [_p('Ano da Gestão', 9, GRAY_TXT, align=TA_RIGHT),_p(str(fiscal_year), 9, BLACK)],
    ]
    geral_t = Table(geral_data, colWidths=[LW, W - LW])
    geral_t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, GRAY_LINE),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('BACKGROUND',    (0, 0), (0, -1), GRAY_ROW),
    ]))
    story.append(geral_t)
    story.append(Spacer(1, 4 * mm))

    # ── DIRETORIA ─────────────────────────────────────────────
    if board_data:
        story.append(section_hdr('DIRETORIA'))
        CW = [42 * mm, W - 42 * mm - 28 * mm - 28 * mm, 28 * mm, 28 * mm]
        dir_rows = []
        for b in board_data:
            dir_rows.append([
                _p(b['role_label'], 8.5, GRAY_TXT, align=TA_RIGHT),
                _p(b['member_name'], 8.5, BLACK),
                _p('CONTATO:', 7.5, GRAY_TXT),
                _p(b['contact'], 8.5, BLACK),
            ])
        dir_t = Table(dir_rows, colWidths=CW)
        dir_t.setStyle(TableStyle([
            ('GRID',          (0, 0), (-1, -1), 0.5, GRAY_LINE),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
            ('BACKGROUND',    (0, 0), (0, -1), GRAY_ROW),
            ('BACKGROUND',    (2, 0), (2, -1), GRAY_ROW),
        ]))
        story.append(dir_t)
        story.append(Spacer(1, 4 * mm))

    # ── SECRETARIAS ───────────────────────────────────────────
    if act_secs_data:
        story.append(section_hdr('SECRETARIAS'))
        CW = [42 * mm, W - 42 * mm - 28 * mm - 28 * mm, 28 * mm, 28 * mm]
        sec_rows = []
        for s in act_secs_data:
            sec_rows.append([
                _p(s['activity_name'], 8.5, GRAY_TXT, align=TA_RIGHT),
                _p(s['member_name'], 8.5, BLACK),
                _p('CONTATO:', 7.5, GRAY_TXT),
                _p(s['contact'], 8.5, BLACK),
            ])
        sec_t = Table(sec_rows, colWidths=CW)
        sec_t.setStyle(TableStyle([
            ('GRID',          (0, 0), (-1, -1), 0.5, GRAY_LINE),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
            ('BACKGROUND',    (0, 0), (0, -1), GRAY_ROW),
            ('BACKGROUND',    (2, 0), (2, -1), GRAY_ROW),
        ]))
        story.append(sec_t)

    story.append(PageBreak())

    # ════════════════════════════════
    # SEÇÃO I — INTRODUÇÃO
    # ════════════════════════════════
    story.append(section_bar_num('I', 'INTRODUÇÃO'))
    story.append(Spacer(1, 4 * mm))

    # Versículo — alinhado à direita, itálico
    if report.get('section_intro_verse') and report['section_intro_verse'].strip():
        verse_lines = report['section_intro_verse'].strip().split('\n')
        for line in verse_lines:
            if line.strip():
                story.append(Paragraph(
                    f'<i>"{line.strip()}"</i>' if not line.strip().startswith('"')
                    else f'<i>{line.strip()}</i>',
                    ParagraphStyle('verse', fontSize=10, textColor=BLACK,
                        fontName='Helvetica-Oblique', alignment=TA_RIGHT,
                        leading=16, spaceAfter=2,
                    )
                ))
        story.append(Spacer(1, 5 * mm))

    render_text(report.get('section_intro'))
    story.append(PageBreak())

    # ════════════════════════════════
    # SEÇÃO II — ATIVIDADES REALIZADAS
    # ════════════════════════════════
    story.append(section_bar_num('II', 'ATIVIDADES REALIZADAS'))
    story.append(Spacer(1, 3 * mm))

    if activities:
        HW = (W - 4 * mm) / 2
        LLW = 18 * mm
        VW = HW - LLW

        # Agrupa por mês
        by_month = {m: [] for m in range(1, 13)}
        for act in activities:
            month_num = int(act['start_date'].split('-')[1])
            by_month[month_num].append(act)

        def make_month_block(month_num, acts):
            m_name = MONTH_NAMES_PT[month_num - 1].upper()
            m_hdr = Table([[_p(m_name, 8.5, WHITE, bold=True)]], colWidths=[HW])
            m_hdr.setStyle(TableStyle([
                ('BACKGROUND',    (0, 0), (-1, -1), TC),
                ('TOPPADDING',    (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ]))

            col_hdr = Table([[
                _p('Dia', 7.5, GRAY_TXT, bold=True, align=TA_CENTER),
                _p('Programação', 7.5, GRAY_TXT, bold=True),
            ]], colWidths=[LLW, VW])
            col_hdr.setStyle(TableStyle([
                ('GRID',          (0, 0), (-1, -1), 0.5, GRAY_LINE),
                ('TOPPADDING',    (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LEFTPADDING',   (0, 0), (-1, -1), 4),
                ('BACKGROUND',    (0, 0), (-1, -1), GRAY_ROW),
            ]))

            act_rows = []
            for act in acts:
                start = _dt.date.fromisoformat(act['start_date'])
                end   = _dt.date.fromisoformat(act['end_date']) if act.get('end_date') else None
                day_str = f"{start.day}/{end.day}" if end and end != start else str(start.day)
                act_rows.append([
                    _p(day_str, 7.5, BLACK, align=TA_CENTER),
                    _p(act['title'], 7.5, BLACK),
                ])

            while len(act_rows) < 3:
                act_rows.append([_p('', 7.5), _p('', 7.5)])

            acts_t = Table(act_rows, colWidths=[LLW, VW])
            acts_t.setStyle(TableStyle([
                ('GRID',           (0, 0), (-1, -1), 0.5, GRAY_LINE),
                ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING',     (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING',  (0, 0), (-1, -1), 3),
                ('LEFTPADDING',    (0, 0), (-1, -1), 4),
                ('RIGHTPADDING',   (0, 0), (-1, -1), 4),
                ('ROWBACKGROUNDS', (0, 0), (-1, -1), [WHITE, GRAY_ROW]),
            ]))

            return Table([[m_hdr], [col_hdr], [acts_t]], colWidths=[HW])

        # Renderiza em 2 colunas: Jan×Jul, Fev×Ago, ...
        for left_m, right_m in zip(range(1, 7), range(7, 13)):
            left_block  = make_month_block(left_m, by_month[left_m])
            right_block = make_month_block(right_m, by_month[right_m])
            pair = Table([[left_block, Spacer(4 * mm, 1), right_block]],
                         colWidths=[HW, 4 * mm, HW])
            pair.setStyle(TableStyle([
                ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
                ('TOPPADDING',    (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(pair)
            story.append(Spacer(1, 3 * mm))
    else:
        story.append(_p('Nenhuma atividade cadastrada.', 9, GRAY_TXT, align=TA_CENTER))

    story.append(PageBreak())

    # ════════════════════════════════
    # SEÇÃO III — RAIO-X
    # ════════════════════════════════
    story.append(section_bar_num('III', 'RAIO-X'))
    story.append(Spacer(1, 4 * mm))

    raio_x_sections = [
        ('Pontos Fortes:',                       report.get('section_raio_x_strong')),
        ('Pontos Fracos:',                        report.get('section_raio_x_weak')),
        ('Objetivos Propostos Alcançados:',       report.get('section_raio_x_achieved')),
        ('Objetivos Propostos Não Alcançados:',   report.get('section_raio_x_not_achieved')),
    ]
    for sub_title, content in raio_x_sections:
        if content and content.strip():
            story.append(Paragraph(sub_title, ParagraphStyle('sub',
                fontSize=10, textColor=BLACK, fontName='Helvetica-Bold',
                spaceBefore=4, spaceAfter=2, leading=14,
            )))
            render_text(content)
            story.append(Spacer(1, 3 * mm))

    story.append(PageBreak())

    # ════════════════════════════════
    # SEÇÃO IV — REGISTROS DE ATIVIDADES (com fotos)
    # ════════════════════════════════
    story.append(section_bar_num('IV', 'REGISTROS DE ATIVIDADES'))

    first_activity = True
    for act in activities:
        photos = [p for p in act.get('photos_bytes', []) if p]

        if first_activity:
            story.append(Spacer(1, 3 * mm))
            first_activity = False
        else:
            story.append(PageBreak())

        start = _dt.date.fromisoformat(act['start_date'])
        end   = _dt.date.fromisoformat(act['end_date']) if act.get('end_date') else None
        if end and end != start:
            date_str = f"{start.day} e {end.day}/{end.month:02d}/{end.year}"
        else:
            date_str = start.strftime('%d/%m/%Y')

        story.append(Paragraph(
            f'{date_str} — <b>{act["title"]}</b>',
            ParagraphStyle('act_title', fontSize=10, textColor=BLACK,
                           fontName='Helvetica', leading=14, spaceAfter=4)
        ))

        if act.get('description'):
            story.append(Paragraph(act['description'], ParagraphStyle('act_desc',
                fontSize=9, textColor=BLACK, fontName='Helvetica',
                alignment=4, leading=14, spaceAfter=6,
            )))

        if not photos:
            story.append(Spacer(1, 4 * mm))
            continue

        try:
            from PIL import Image as PILImage
            PIL_available = True
        except ImportError:
            PIL_available = False

        def _make_img(photo_bytes, max_w, max_h):
            """Cria Image respeitando proporção."""
            try:
                if PIL_available:
                    pil = PILImage.open(io.BytesIO(photo_bytes))
                    ow, oh = pil.size
                    ratio = min(max_w / (ow * 0.352778), max_h / (oh * 0.352778))
                    iw = ow * 0.352778 * ratio
                    ih = oh * 0.352778 * ratio
                else:
                    iw, ih = max_w, max_h
                img = Image(io.BytesIO(photo_bytes), width=iw, height=ih)
                img.hAlign = 'CENTER'
                return img
            except Exception:
                return Spacer(1, 1)

        n = len(photos)
        MAX_H = 180 * mm

        if n == 1:
            story.append(_make_img(photos[0], W, MAX_H))

        elif n == 2:
            half = (W - 3 * mm) / 2
            row = Table([
                [_make_img(photos[0], half, MAX_H / 2),
                 _make_img(photos[1], half, MAX_H / 2)]
            ], colWidths=[half, half])
            row.setStyle(TableStyle([
                ('VALIGN',  (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN',   (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(row)

        elif n == 3:
            half = (W - 3 * mm) / 2
            row_h = MAX_H / 2 - 3 * mm
            top_row = Table([
                [_make_img(photos[0], half, row_h),
                 _make_img(photos[1], half, row_h)]
            ], colWidths=[half, half])
            top_row.setStyle(TableStyle([
                ('VALIGN',  (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN',   (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(top_row)
            story.append(Spacer(1, 3 * mm))
            bot = _make_img(photos[2], W / 2, row_h)
            bot_row = Table([[bot]], colWidths=[W])
            bot_row.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
            story.append(bot_row)

        else:  # 4 fotos — grade 2×2
            half = (W - 3 * mm) / 2
            row_h = MAX_H / 2 - 3 * mm
            for i in range(0, 4, 2):
                pair = Table([
                    [_make_img(photos[i], half, row_h),
                     _make_img(photos[i + 1], half, row_h)]
                ], colWidths=[half, half])
                pair.setStyle(TableStyle([
                    ('VALIGN',  (0, 0), (-1, -1), 'MIDDLE'),
                    ('ALIGN',   (0, 0), (-1, -1), 'CENTER'),
                    ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ]))
                story.append(pair)
                if i == 0:
                    story.append(Spacer(1, 3 * mm))

    # ════════════════════════════════
    # SEÇÃO V — PALAVRA FINAL
    # ════════════════════════════════
    final_word = report.get('section_final_word', '')
    if final_word and final_word.strip():
        story.append(PageBreak())
        story.append(section_bar_num('V', 'PALAVRA FINAL'))
        story.append(Spacer(1, 4 * mm))
        render_text(final_word)

        story.append(Spacer(1, 10 * mm))

        # Nome e cargo — alinhado à direita, itálico como no modelo
        sign_name = report.get('section_final_sign_name', '')
        sign_role = report.get('section_final_sign_role', '')

        if not sign_name:
            pres = next((b for b in board_data if b.get('role_label') == 'Presidente'), None)
            if pres:
                sign_name = pres.get('member_name', '')
                sign_role = f"Presidente da {org_data.get('name','')} {fiscal_year}"

        if sign_name:
            story.append(Paragraph(sign_name, ParagraphStyle('sig_name',
                fontSize=10, textColor=BLACK, alignment=TA_RIGHT,
                fontName='Helvetica-Bold', leading=14,
            )))
        if sign_role:
            story.append(Paragraph(f'<i>{sign_role}</i>', ParagraphStyle('sig_role',
                fontSize=9, textColor=colors.HexColor('#64748b'), alignment=TA_RIGHT,
                fontName='Helvetica-Oblique', leading=12,
            )))

    doc.build(story,
        onFirstPage=_make_header_footer,
        onLaterPages=_make_header_footer,
    )
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


def generate_uph_stat_report(
    org_data: dict,
    fiscal_year: int,
    stat: dict,
) -> bytes:
    """Gera o Relatório de Estatística no modelo oficial da CNHP/UPH"""

    buf = io.BytesIO()
    ML = MR = 15 * mm
    W  = A4[0] - ML - MR

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=15 * mm, bottomMargin=15 * mm)

    YELLOW    = colors.HexColor('#FFC000')
    YELLOW_LT = colors.HexColor('#FFE699')
    DARK      = colors.HexColor('#1F3864')
    BK        = colors.black
    GY        = colors.HexColor('#F2F2F2')

    def _p(txt, size=9, color=BK, bold=False, align=TA_LEFT, italic=False):
        font = 'Helvetica-BoldOblique' if bold and italic else \
               'Helvetica-Bold' if bold else \
               'Helvetica-Oblique' if italic else 'Helvetica'
        return Paragraph(str(txt or ''), ParagraphStyle('_',
            fontSize=size, textColor=color, fontName=font,
            alignment=align, leading=size * 1.4, wordWrap='LTR',
        ))

    story = []

    # ── Cabeçalho principal ──────────────────────────────────
    hdr_logo  = _p('UPH',  14, DARK, bold=True, align=TA_CENTER)
    hdr_ipb   = _p('IGREJA\nPRESBITERIANA\ndoBRASIL', 8, DARK, bold=True, align=TA_CENTER)

    hdr_title = Table([
        [_p('CONFEDERAÇÃO NACIONAL DE', 10, DARK, bold=True, align=TA_CENTER)],
        [_p('HOMENS PRESBITERIANOS - CNHP', 10, DARK, bold=True, align=TA_CENTER)],
        [Spacer(1, 2 * mm)],
        [_p('RELATÓRIO DE ESTATÍSTICA', 12, DARK, bold=True, align=TA_CENTER)],
    ], colWidths=[W - 50 * mm])
    hdr_title.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    hdr_outer = Table([[
        Table([[hdr_logo]], colWidths=[25 * mm]),
        hdr_title,
        Table([[hdr_ipb]], colWidths=[25 * mm]),
    ]], colWidths=[25 * mm, W - 50 * mm, 25 * mm])
    hdr_outer.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 1.5, BK),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, BK),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
    ]))
    story.append(hdr_outer)

    # ── Linha de identificação do nível e ano ────────────────
    org_type = org_data.get('organization_type', 'local_ump')
    is_fed   = org_type == 'federation'

    level_row = Table([[
        _p('UPH, FEDERAÇÃO, CONFEDERAÇÃO SINODAL,\nCONFEDERAÇÃO NACIONAL',
           8, DARK, bold=True, align=TA_CENTER),
        Table([[
            _p('ANO', 8, DARK, bold=True),
            _p(f'  {fiscal_year}', 8, BK, bold=True),
        ]], colWidths=[15 * mm, 25 * mm]),
    ]], colWidths=[W - 40 * mm, 40 * mm])
    level_row.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 1, BK),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, BK),
        ('BACKGROUND',    (0, 0), (-1, -1), YELLOW),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
    ]))
    story.append(level_row)

    # ── Seções de identificação ──────────────────────────────
    def id_section(label, value, bg=YELLOW_LT):
        t = Table([[
            _p(label, 8, DARK, bold=True),
            _p(value, 8, BK),
        ]], colWidths=[80 * mm, W - 80 * mm])
        t.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.5, BK),
            ('INNERGRID',     (0, 0), (-1, -1), 0.5, BK),
            ('BACKGROUND',    (0, 0), (0, 0),   bg),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ]))
        return t

    def section_hdr(txt, level_num):
        t = Table([[
            _p(f'{level_num}) {txt}', 8, DARK, bold=True, align=TA_CENTER)
        ]], colWidths=[W])
        t.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.5, BK),
            ('BACKGROUND',    (0, 0), (-1, -1), YELLOW),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        return t

    org_name = org_data.get('name', '')
    fed_name = org_data.get('federation_name', '') if not is_fed else org_name
    syn_name = org_data.get('synodal_name', '')

    story.append(section_hdr('UPH (ENVIAR À FEDERAÇÃO)', 1))
    story.append(id_section('NOME DA UPH:', org_name if not is_fed else ''))
    story.append(section_hdr('FEDERAÇÃO PARA A CONFEDERAÇÃO SINODAL', 2))
    story.append(id_section('NOME E SIGLA DA FEDERAÇÃO:', fed_name))
    story.append(section_hdr('CONFEDERAÇÃO SINODAL PARA A CONFEDERAÇÃO NACIONAL', 3))
    story.append(id_section('NOME E SIGLA DA CONFED. SINODAL:', syn_name))
    story.append(section_hdr('CONFEDERAÇÃO NACIONAL. ATUALIZADO EM', 4))

    # ── Cabeçalho da tabela de estatísticas ─────────────────
    col_widths = [W * 0.45, W * 0.14, W * 0.14, W * 0.14, W * 0.13]

    thead = Table([[
        _p('ITEM',                  8, DARK, bold=True, align=TA_CENTER),
        _p('QUANT.\nANO\nATUAL',    7, DARK, bold=True, align=TA_CENTER),
        _p('Δ% ANO\nATUAL',         7, DARK, bold=True, align=TA_CENTER),
        _p('QUANT.\nANO\nANTERIOR', 7, DARK, bold=True, align=TA_CENTER),
        _p('Δ%\nVARIAÇÃO',          7, DARK, bold=True, align=TA_CENTER),
    ]], colWidths=col_widths)
    thead.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 0.5, BK),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, BK),
        ('BACKGROUND',    (0, 0), (-1, -1), YELLOW),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
    ]))
    story.append(thead)

    # ── Linhas dos itens ─────────────────────────────────────
    items = [
        (1, 'Quantidade de Homens na igreja',         None),
        (2, 'Quantidade de Homens na UPH',            '60%'),
        (3, 'Quantidade de Oficiais na igreja',       None),
        (4, 'Quantidade de Oficiais sócios da UPH',  None),
        (5, 'Quantidade de Congregações',             None),
        (6, 'Quantidade de Igrejas',                  None),
        (7, 'Quantidade de UPHs',                     '50%'),
    ]

    for num, desc, nota in items:
        cur  = stat.get(f'item{num}_current', 0) or 0
        prev = stat.get(f'item{num}_previous', 0) or 0
        dlt  = stat.get(f'item{num}_delta')

        def fmt_num(n):
            return str(n) if n else ''

        def fmt_delta(d, p):
            if d is None or p == 0:
                return ''
            return f'{d:+.1f}%'

        delta_color = BK
        if dlt is not None and prev > 0:
            delta_color = colors.HexColor('#166534') if dlt >= 0 else colors.HexColor('#991b1b')

        desc_content = f'{num}. {desc}'
        if nota:
            desc_content += f'   <font size="7" color="#1F3864"><b>{nota}</b></font>'

        row_data = [
            Paragraph(desc_content, ParagraphStyle('item',
                fontSize=8, textColor=BK, fontName='Helvetica',
                leading=11, leftIndent=3,
            )),
            _p(fmt_num(cur),          8, BK,          align=TA_CENTER),
            _p('',                    8, BK,          align=TA_CENTER),
            _p(fmt_num(prev),         8, BK,          align=TA_CENTER),
            _p(fmt_delta(dlt, prev),  8, delta_color, align=TA_CENTER),
        ]

        row_bg = YELLOW_LT if num % 2 == 0 else colors.white
        row_t = Table([row_data], colWidths=col_widths)
        row_t.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.5, BK),
            ('INNERGRID',     (0, 0), (-1, -1), 0.5, BK),
            ('BACKGROUND',    (0, 0), (-1, -1), row_bg),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING',   (0, 0), (-1, -1), 3),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ]))
        story.append(row_t)

    # ── Orientações ──────────────────────────────────────────
    story.append(Spacer(1, 2 * mm))

    orient_hdr = Table([[
        _p('PREENCHIMENTO, ENCAMINHAMENTO, ORIENTAÇÕES',
           8, DARK, bold=True, align=TA_CENTER),
    ], [
        _p('(NÃO PREENCHER À MÃO)', 8, DARK, bold=True, align=TA_CENTER),
    ]], colWidths=[W])
    orient_hdr.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 0.5, BK),
        ('BACKGROUND',    (0, 0), (-1, -1), YELLOW),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(orient_hdr)

    orient_items = [
        '1) A UPH preenche os itens 1 a 5 e informa à Federação',
        '2) A Federação soma os itens 1 a 5 dos relatórios das UPHs, transcreve, preenche os itens 6 e 7 e informa à Confederação Sinodal',
        '3) A Sinodal soma os itens 1 a 7 dos relatórios das Federações, transcreve, preenche os itens 8 e 9 e informa à Confederação Nacional',
        '4) A CNHP, através da Sec. de Estatística, soma os itens 1 a 9, transcreve, preenche os 10 e 11 e informa às Confederações Sinodais, estas às Federações, e estas às UPHs',
    ]
    for i, txt in enumerate(orient_items):
        bg = YELLOW_LT if i % 2 == 0 else colors.white
        ot = Table([[_p(txt, 7.5, BK, align=TA_CENTER)]], colWidths=[W])
        ot.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.3, BK),
            ('BACKGROUND',    (0, 0), (-1, -1), bg),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ]))
        story.append(ot)

    verse_t = Table([[
        _p('"Portanto, meus amados irmãos, sede firmes e sempre abundantes na '
           'obra do Senhor, sabendo que, no Senhor, o vosso trabalho não é vão". '
           '(I Co 15.58)', 7.5, BK, italic=True, align=TA_CENTER)
    ]], colWidths=[W])
    verse_t.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 0.3, BK),
        ('BACKGROUND',    (0, 0), (-1, -1), YELLOW_LT),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
    ]))
    story.append(verse_t)

    doc.build(story)
    return buf.getvalue()

    doc.build(story)
    return buf.getvalue()