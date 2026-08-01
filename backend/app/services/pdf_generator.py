import io
import re
import datetime
import gc
import logging
import time
import concurrent.futures
import threading
from PIL import Image as _PILImage
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Image, Paragraph, Flowable
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

logger = logging.getLogger(__name__)

GRAY_ROW  = colors.HexColor('#f5f7fa')
GRAY_LINE = colors.HexColor('#e2e8f0')
GRAY_TXT  = colors.HexColor('#64748b')
BLACK     = colors.HexColor('#1e293b')
GREEN     = colors.HexColor('#16a34a')
RED_C     = colors.HexColor('#dc2626')
WHITE     = colors.white
YELLOW_BG = colors.HexColor('#fffde7')
BLUE_DEF  = colors.HexColor('#1a2a6c')

_TC_CACHE = {}

def _tc(hex_color):
    if not hex_color:
        return BLUE_DEF
    s = str(hex_color).strip().lower()
    if s not in _TC_CACHE:
        try:
            _TC_CACHE[s] = colors.HexColor(s)
        except Exception:
            _TC_CACHE[s] = BLUE_DEF
    return _TC_CACHE[s]


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


_STYLE_CACHE = {}

def _get_paragraph_style(size=10, color=BLACK, bold=False, align=TA_LEFT,
                         leading=None, indent=0, space_before=0, space_after=2,
                         first_line_indent=0, font_name=None):
    if font_name is None:
        font_name = 'Helvetica-Bold' if bold else 'Helvetica'
    leading_val = leading if leading is not None else (size * 1.5)
    indent_val = indent * mm if isinstance(indent, (int, float)) else indent
    first_indent_val = first_line_indent * mm if isinstance(first_line_indent, (int, float)) else first_line_indent
    cache_key = (size, str(color), font_name, align, leading_val, indent_val, space_before, space_after, first_indent_val)
    if cache_key not in _STYLE_CACHE:
        _STYLE_CACHE[cache_key] = ParagraphStyle(
            f'ps_{len(_STYLE_CACHE)}',
            fontSize=size,
            textColor=color,
            fontName=font_name,
            alignment=align,
            leading=leading_val,
            leftIndent=indent_val,
            firstLineIndent=first_indent_val,
            spaceBefore=space_before,
            spaceAfter=space_after,
        )
    return _STYLE_CACHE[cache_key]


def _ps(size=8, color=BLACK, bold=False, align=TA_LEFT):
    return _get_paragraph_style(size=size, color=color, bold=bold, align=align, space_after=0, space_before=0, leading=size * 1.4)


def _p(txt, size=10, color=BLACK, bold=False, align=TA_LEFT,
       leading=None, indent=0, space_before=0, space_after=2):
    style = _get_paragraph_style(size=size, color=color, bold=bold, align=align,
                                leading=leading, indent=indent,
                                space_before=space_before, space_after=space_after)
    return Paragraph(str(txt or ''), style)


def _logo(logo_bytes, w_mm, h_mm):
    if not logo_bytes:
        return None
    try:
        img = Image(io.BytesIO(logo_bytes), width=w_mm*mm, height=h_mm*mm)
        return img
    except:
        return None


def _resize_image(img_bytes: bytes, max_width: int = 800) -> bytes:
    try:
        pil = _PILImage.open(io.BytesIO(img_bytes))
        if pil.mode in ('RGBA', 'P', 'LA'):
            pil = pil.convert('RGB')
        if pil.width > max_width:
            ratio = max_width / pil.width
            pil = pil.resize((max_width, int(pil.height * ratio)), _PILImage.LANCZOS)
        buf = io.BytesIO()
        pil.save(buf, format='JPEG', quality=75, optimize=True)
        return buf.getvalue()
    except Exception:
        return img_bytes


def _download_b2(client, bucket, url):
    try:
        match = re.search(r'(?:/file/[^/]+/|/)(activities/.+|receipts/.+|logos/.+|reports/.+|pix-qr/.+|signatures/.+)$', url)
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
    gc.collect()
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════
# HELPER PARALELO DE IMAGENS E LAZY IMAGE OTIMIZADA
# ═══════════════════════════════════════════════════════════════

def _extract_b2_key(key_or_url: str, bucket: str) -> str:
    if not key_or_url:
        return ""
    match = re.search(r'(?:/file/[^/]+/|/)(activities/.+|receipts/.+|logos/.+|reports/.+|pix-qr/.+|signatures/.+)$', key_or_url)
    if match:
        return match.group(1)
    return key_or_url


import httpx

def _download_photo_http(photo_key: str) -> bytes:
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.r2_public_domain:
        return None
    url = f"{settings.r2_public_domain.rstrip('/')}/{photo_key.lstrip('/')}"
    try:
        resp = httpx.get(url, timeout=10.0)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.error("Falha no download via HTTP [url: %s]: %s", url, e)
    return None


def _process_single_photo_worker(b2_client, bucket, photo_key, photo_bytes, image_cache, cache_lock):
    cache_key = photo_key if photo_key else (id(photo_bytes) if photo_bytes else None)
    if not cache_key:
        return None

    with cache_lock:
        if cache_key in image_cache:
            return image_cache[cache_key]

    raw_bytes = photo_bytes
    if raw_bytes is None and photo_key:
        clean_key = _extract_b2_key(photo_key, bucket)
        # Tenta primeiro por HTTP (muito mais rápido e consome menos overhead)
        raw_bytes = _download_photo_http(clean_key)

        # Fallback para o cliente tradicional S3 se o download HTTP falhar ou não estiver configurado
        if not raw_bytes and b2_client:
            try:
                resp = b2_client.get_object(Bucket=bucket, Key=clean_key)
                raw_bytes = resp['Body'].read()
            except Exception as e:
                logger.error("Falha no download direto da foto no B2/R2 [key: %s]: %s", clean_key, e)
                raw_bytes = None

    if not raw_bytes:
        res = (b'', 1, 1)
        with cache_lock:
            image_cache[cache_key] = res
        return res

    try:
        from PIL import Image as PILImage, ImageOps as PILImageOps
        with PILImage.open(io.BytesIO(raw_bytes)) as pil_img:
            pil_img = PILImageOps.exif_transpose(pil_img)
            pil_img.thumbnail((800, 800), PILImage.LANCZOS)
            if pil_img.mode in ('RGBA', 'P', 'LA'):
                pil_img = pil_img.convert('RGB')
            out_io = io.BytesIO()
            pil_img.save(out_io, format='JPEG', quality=80, optimize=True)
            proc_bytes = out_io.getvalue()
            ow, oh = pil_img.size

        del raw_bytes
        res = (proc_bytes, ow, oh)
        with cache_lock:
            image_cache[cache_key] = res
        return res
    except Exception as e:
        logger.error("Falha no redimensionamento da foto [key: %s]: %s", photo_key, e)
        res = (b'', 1, 1)
        with cache_lock:
            image_cache[cache_key] = res
        return res


def _download_and_process_photos_parallel(activities: list, b2_client, bucket: str, image_cache: dict) -> int:
    tasks = []
    seen = set()
    for act in activities:
        keys = act.get('photo_keys', [])
        bytes_list = act.get('photos_bytes', [])
        if keys:
            for k in keys:
                if k and k not in seen:
                    seen.add(k)
                    tasks.append((k, None))
        elif bytes_list:
            for b in bytes_list:
                if b and id(b) not in seen:
                    seen.add(id(b))
                    tasks.append((None, b))

    if not tasks:
        return 0

    cache_lock = threading.Lock()
    # Aumentado de 3 para no máximo 20 workers simultâneos para downloads ultrarrápidos no Cloudflare
    max_workers = min(20, len(tasks))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_process_single_photo_worker, b2_client, bucket, k, b, image_cache, cache_lock)
            for k, b in tasks
        ]
        concurrent.futures.wait(futures)

    gc.collect()
    return len(tasks)


class LazyImage(Flowable):
    def __init__(self, b2_client, bucket, photo_key=None, photo_bytes=None, max_w=0, max_h=0, image_cache=None):
        Flowable.__init__(self)
        self.b2_client = b2_client
        self.bucket = bucket
        self.photo_key = photo_key
        self.photo_bytes = photo_bytes
        self.max_w = max_w
        self.max_h = max_h
        self.image_cache = image_cache
        self.width = max_w
        self.height = max_h
        self._processed_bytes = None
        self._calculate_dimensions()

    def _calculate_dimensions(self):
        cache_key = self.photo_key if self.photo_key else (id(self.photo_bytes) if self.photo_bytes else None)
        if self.image_cache and cache_key and cache_key in self.image_cache:
            proc_bytes, ow, oh = self.image_cache[cache_key]
            if proc_bytes and ow > 0 and oh > 0:
                self._processed_bytes = proc_bytes
                ratio = min(self.max_w / (ow * 0.352778), self.max_h / (oh * 0.352778))
                self.width = ow * 0.352778 * ratio
                self.height = oh * 0.352778 * ratio
                return

        self._load_and_process()

    def _load_and_process(self):
        if self._processed_bytes is not None:
            return
        try:
            raw_bytes = self.photo_bytes
            if raw_bytes is None and self.photo_key and self.b2_client:
                clean_key = _extract_b2_key(self.photo_key, self.bucket)
                resp = self.b2_client.get_object(Bucket=self.bucket, Key=clean_key)
                raw_bytes = resp['Body'].read()

            if not raw_bytes:
                self.width = 1
                self.height = 1
                self._processed_bytes = b''
                return

            from PIL import Image as PILImage, ImageOps as PILImageOps
            with PILImage.open(io.BytesIO(raw_bytes)) as pil_img:
                pil_img = PILImageOps.exif_transpose(pil_img)
                pil_img.thumbnail((800, 800), PILImage.LANCZOS)
                if pil_img.mode in ('RGBA', 'P', 'LA'):
                    pil_img = pil_img.convert('RGB')
                out_io = io.BytesIO()
                pil_img.save(out_io, format='JPEG', quality=80, optimize=True)
                self._processed_bytes = out_io.getvalue()
                ow, oh = pil_img.size

            ratio = min(self.max_w / (ow * 0.352778), self.max_h / (oh * 0.352778))
            self.width = ow * 0.352778 * ratio
            self.height = oh * 0.352778 * ratio
        except Exception as e:
            logger.error("Erro ao carregar imagem no LazyImage [key: %s]: %s", self.photo_key, e)
            self.width = 1
            self.height = 1
            self._processed_bytes = b''

    def wrap(self, availWidth, availHeight):
        if self._processed_bytes is None:
            self._load_and_process()
        return self.width, self.height

    def draw(self):
        if not self._processed_bytes:
            return
        try:
            from reportlab.platypus import Image as RLImage
            img = RLImage(io.BytesIO(self._processed_bytes), width=self.width, height=self.height)
            img.hAlign = 'CENTER'
            img.drawOn(self.canv, 0, 0)
        except Exception as e:
            logger.error("Erro ao desenhar imagem no canvas [key: %s]: %s", self.photo_key, e)


# ═══════════════════════════════════════════════════════════════
# SUBFUNÇÕES MODULARES DO RELATÓRIO DE ATIVIDADES
# ═══════════════════════════════════════════════════════════════

def _render_text_to_story(text_content, story):
    if not text_content:
        return
    body_style = _get_paragraph_style(
        size=10, color=BLACK, bold=False, align=4, leading=16, first_line_indent=10, space_after=2
    )
    for para in text_content.split('\n'):
        stripped = para.strip()
        if not stripped:
            story.append(Spacer(1, 2 * mm))
            continue
        story.append(Paragraph(stripped, body_style))


def _build_header_section(logo_bytes, ipb_logo_bytes, org_data, fiscal_year, W):
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

    return [
        hdr,
        Spacer(1, 5 * mm),
        HRFlowable(width=W, thickness=0.5, color=GRAY_LINE),
        Spacer(1, 4 * mm),
    ]


def _build_general_data_section(org_data, fiscal_year, W, section_hdr_func):
    items = [section_hdr_func('DADOS GERAIS')]
    LW = 45 * mm
    org_name   = org_data.get('name', '')
    presbytery = org_data.get('presbytery_name', '')

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
    items.append(geral_t)
    items.append(Spacer(1, 4 * mm))
    return items


def _build_board_section(board_data, W, section_hdr_func):
    if not board_data:
        return []
    items = [section_hdr_func('DIRETORIA')]
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
    items.append(dir_t)
    items.append(Spacer(1, 4 * mm))
    return items


def _build_secretaries_section(act_secs_data, W, section_hdr_func):
    if not act_secs_data:
        return []
    items = [section_hdr_func('SECRETARIAS')]
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
    items.append(sec_t)
    return items


def _build_intro_section(report, W, TC, section_bar_num_func):
    items = [
        section_bar_num_func('I', 'INTRODUÇÃO'),
        Spacer(1, 4 * mm),
    ]
    if report.get('section_intro_verse') and report['section_intro_verse'].strip():
        verse_lines = report['section_intro_verse'].strip().split('\n')
        verse_style = _get_paragraph_style(
            size=10, color=BLACK, bold=False, align=TA_RIGHT,
            leading=16, space_after=2, font_name='Helvetica-Oblique'
        )
        for line in verse_lines:
            if line.strip():
                txt = f'<i>"{line.strip()}"</i>' if not line.strip().startswith('"') else f'<i>{line.strip()}</i>'
                items.append(Paragraph(txt, verse_style))
        items.append(Spacer(1, 5 * mm))

    _render_text_to_story(report.get('section_intro'), items)
    return items


def _build_activities_list_section(activities, W, TC, section_bar_num_func):
    items = [
        section_bar_num_func('II', 'ATIVIDADES REALIZADAS'),
        Spacer(1, 3 * mm),
    ]

    MONTH_NAMES_PT = [
        'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
    ]

    if activities:
        HW = (W - 4 * mm) / 2
        LLW = 18 * mm
        VW = HW - LLW

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
                start = datetime.date.fromisoformat(act['start_date'])
                end   = datetime.date.fromisoformat(act['end_date']) if act.get('end_date') else None
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
            items.append(pair)
            items.append(Spacer(1, 3 * mm))
    else:
        items.append(_p('Nenhuma atividade cadastrada.', 9, GRAY_TXT, align=TA_CENTER))

    return items


def _build_raio_x_section(report, W, TC, section_bar_num_func):
    items = [
        section_bar_num_func('III', 'RAIO-X'),
        Spacer(1, 4 * mm),
    ]
    sub_title_style = _get_paragraph_style(
        size=10, color=BLACK, bold=True, space_before=4, space_after=2, leading=14
    )

    raio_x_sections = [
        ('Pontos Fortes:',                       report.get('section_raio_x_strong')),
        ('Pontos Fracos:',                        report.get('section_raio_x_weak')),
        ('Objetivos Propostos Alcançados:',       report.get('section_raio_x_achieved')),
        ('Objetivos Propostos Não Alcançados:',   report.get('section_raio_x_not_achieved')),
    ]
    for sub_title, content in raio_x_sections:
        if content and content.strip():
            items.append(Paragraph(sub_title, sub_title_style))
            _render_text_to_story(content, items)
            items.append(Spacer(1, 3 * mm))

    return items


def _build_activity_photos_section(activities, b2, bucket, W, TC, image_cache, section_bar_num_func):
    items = [
        section_bar_num_func('IV', 'REGISTROS DE ATIVIDADES'),
    ]

    act_title_style = _get_paragraph_style(
        size=10, color=BLACK, bold=False, font_name='Helvetica', leading=14, space_after=4
    )
    act_desc_style = _get_paragraph_style(
        size=9, color=BLACK, bold=False, font_name='Helvetica', align=4, leading=14, space_after=6
    )

    first_activity = True
    for act in activities:
        keys = act.get('photo_keys', [])
        bytes_list = act.get('photos_bytes', [])

        photos_data = []
        if keys:
            for k in keys:
                photos_data.append((k, None))
        elif bytes_list:
            for b in bytes_list:
                if b:
                    photos_data.append((None, b))

        if first_activity:
            items.append(Spacer(1, 3 * mm))
            first_activity = False
        else:
            items.append(PageBreak())

        start = datetime.date.fromisoformat(act['start_date'])
        end   = datetime.date.fromisoformat(act['end_date']) if act.get('end_date') else None
        if end and end != start:
            date_str = f"{start.day} e {end.day}/{end.month:02d}/{end.year}"
        else:
            date_str = start.strftime('%d/%m/%Y')

        items.append(Paragraph(f'{date_str} — <b>{act["title"]}</b>', act_title_style))

        if act.get('description'):
            items.append(Paragraph(act['description'], act_desc_style))

        if not photos_data:
            items.append(Spacer(1, 4 * mm))
            continue

        n = len(photos_data)
        MAX_H = 180 * mm

        if n == 1:
            items.append(LazyImage(b2, bucket, photo_key=photos_data[0][0], photo_bytes=photos_data[0][1], max_w=W, max_h=MAX_H, image_cache=image_cache))

        elif n == 2:
            half = (W - 3 * mm) / 2
            row = Table([
                [LazyImage(b2, bucket, photo_key=photos_data[0][0], photo_bytes=photos_data[0][1], max_w=half, max_h=MAX_H / 2, image_cache=image_cache),
                 LazyImage(b2, bucket, photo_key=photos_data[1][0], photo_bytes=photos_data[1][1], max_w=half, max_h=MAX_H / 2, image_cache=image_cache)]
            ], colWidths=[half, half])
            row.setStyle(TableStyle([
                ('VALIGN',  (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN',   (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            items.append(row)

        elif n == 3:
            half = (W - 3 * mm) / 2
            row_h = MAX_H / 2 - 3 * mm
            top_row = Table([
                [LazyImage(b2, bucket, photo_key=photos_data[0][0], photo_bytes=photos_data[0][1], max_w=half, max_h=row_h, image_cache=image_cache),
                 LazyImage(b2, bucket, photo_key=photos_data[1][0], photo_bytes=photos_data[1][1], max_w=half, max_h=row_h, image_cache=image_cache)]
            ], colWidths=[half, half])
            top_row.setStyle(TableStyle([
                ('VALIGN',  (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN',   (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            items.append(top_row)
            items.append(Spacer(1, 3 * mm))
            bot = LazyImage(b2, bucket, photo_key=photos_data[2][0], photo_bytes=photos_data[2][1], max_w=W / 2, max_h=row_h, image_cache=image_cache)
            bot_row = Table([[bot]], colWidths=[W])
            bot_row.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
            items.append(bot_row)

        else:  # 4 fotos — grade 2×2
            half = (W - 3 * mm) / 2
            row_h = MAX_H / 2 - 3 * mm
            for i in range(0, 4, 2):
                pair = Table([
                    [LazyImage(b2, bucket, photo_key=photos_data[i][0], photo_bytes=photos_data[i][1], max_w=half, max_h=row_h, image_cache=image_cache),
                     LazyImage(b2, bucket, photo_key=photos_data[i + 1][0], photo_bytes=photos_data[i + 1][1], max_w=half, max_h=row_h, image_cache=image_cache)]
                ], colWidths=[half, half])
                pair.setStyle(TableStyle([
                    ('VALIGN',  (0, 0), (-1, -1), 'MIDDLE'),
                    ('ALIGN',   (0, 0), (-1, -1), 'CENTER'),
                    ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ]))
                items.append(pair)
                if i == 0:
                    items.append(Spacer(1, 3 * mm))

    return items


def _build_final_word_section(report, board_data, org_data, fiscal_year, W, TC, section_bar_num_func):
    final_word = report.get('section_final_word', '')
    if not (final_word and final_word.strip()):
        return []

    items = [
        PageBreak(),
        section_bar_num_func('V', 'PALAVRA FINAL'),
        Spacer(1, 4 * mm),
    ]
    _render_text_to_story(final_word, items)
    items.append(Spacer(1, 10 * mm))

    sign_name = report.get('section_final_sign_name', '')
    sign_role = report.get('section_final_sign_role', '')

    if not sign_name:
        pres = next((b for b in board_data if b.get('role_label') == 'Presidente'), None)
        if pres:
            sign_name = pres.get('member_name', '')
            sign_role = f"Presidente da {org_data.get('name','')} {fiscal_year}"

    if sign_name:
        sig_name_style = _get_paragraph_style(
            size=10, color=BLACK, bold=True, align=TA_RIGHT, leading=14
        )
        items.append(Paragraph(sign_name, sig_name_style))
    if sign_role:
        sig_role_style = _get_paragraph_style(
            size=9, color=_tc('#64748b'), bold=False, align=TA_RIGHT,
            leading=12, font_name='Helvetica-Oblique'
        )
        items.append(Paragraph(f'<i>{sign_role}</i>', sig_role_style))

    return items


# ═══════════════════════════════════════════════════════════════
# RELATÓRIO DE ATIVIDADES (ORQUESTRADOR PRINCIPAL)
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
    b2_client = None,
) -> bytes:
    """Gera o Relatório de Atividades no modelo oficial (altamente otimizado)."""
    t_start = time.perf_counter()

    from app.services.storage import _get_client
    from app.core.config import get_settings

    b2 = b2_client if b2_client is not None else _get_client()
    settings_obj = get_settings()
    bucket = settings_obj.b2_bucket_name

    # 1. Processamento e download paralelo de imagens com cache temporário em memória
    image_cache = {}
    photo_count = _download_and_process_photos_parallel(activities, b2, bucket, image_cache)
    t_photos = time.perf_counter()

    buf = io.BytesIO()
    ML = MR = 15 * mm
    W = A4[0] - ML - MR
    TC = _tc(org_data.get('theme_color', '#1a2a6c'))

    # Pre-criar ImageReaders para logos do cabeçalho uma única vez
    ipb_reader = None
    if ipb_logo_bytes:
        try:
            from reportlab.lib.utils import ImageReader
            ipb_reader = ImageReader(io.BytesIO(ipb_logo_bytes))
        except Exception:
            pass

    org_reader = None
    if logo_bytes:
        try:
            from reportlab.lib.utils import ImageReader
            org_reader = ImageReader(io.BytesIO(logo_bytes))
        except Exception:
            pass

    # Cabeçalho e rodapé em todas as páginas
    def _make_header_footer(canvas_obj, doc_obj):
        canvas_obj.saveState()
        W_page = A4[0]
        ML_page = ML

        # ── Cabeçalho (a partir da 2ª página)
        if doc_obj.page > 1:
            canvas_obj.setStrokeColor(TC)
            canvas_obj.setLineWidth(0.5)

            # Logo IPB
            if ipb_reader:
                try:
                    canvas_obj.drawImage(ipb_reader, ML_page, A4[1]-13*mm,
                                         width=9*mm, height=9*mm,
                                         preserveAspectRatio=True, mask='auto')
                except Exception:
                    pass

            # Logo da org
            if org_reader:
                try:
                    canvas_obj.drawImage(org_reader, W_page-MR-9*mm, A4[1]-13*mm,
                                         width=9*mm, height=9*mm,
                                         preserveAspectRatio=True, mask='auto')
                except Exception:
                    pass

            # Título central
            canvas_obj.setFont('Helvetica-Bold', 8)
            canvas_obj.setFillColor(colors.black)
            canvas_obj.drawCentredString(
                W_page/2, A4[1]-9*mm,
                'RELATÓRIO DE ATIVIDADES'
            )
            canvas_obj.setFont('Helvetica', 7)
            canvas_obj.setFillColor(_tc('#64748b'))
            canvas_obj.drawCentredString(
                W_page/2, A4[1]-13*mm,
                f'Gestão {fiscal_year}  ·  {org_data.get("name","")}'
            )

            # Linha separadora do cabeçalho
            canvas_obj.setStrokeColor(_tc('#e2e8f0'))
            canvas_obj.line(ML_page, A4[1]-15*mm, W_page-MR, A4[1]-15*mm)

        # ── Rodapé em todas as páginas ──
        canvas_obj.setStrokeColor(_tc('#e2e8f0'))
        canvas_obj.line(ML_page, 12*mm, W_page-MR, 12*mm)

        # Lema/texto à esquerda no rodapé (configurável)
        canvas_obj.setFont('Helvetica', 6.5)
        canvas_obj.setFillColor(_tc('#94a3b8'))
        soc_type = str(org_data.get('society_type', 'UMP')).upper()
        if soc_type == 'UPH':
            default_footer = 'CONFIANÇA EM JESUS, ENTUSIASMO NA AÇÃO E UNIÃO FRATERNAL'
        else:
            default_footer = 'ALEGRES NA ESPERANÇA – FORTES NA FÉ – DEDICADOS NO AMOR – UNIDOS NO TRABALHO'
        footer_text = org_data.get('footer_text') or default_footer
        canvas_obj.drawCentredString(W_page/2, 8*mm, footer_text)

        # Número da página à direita
        canvas_obj.setFont('Helvetica', 7)
        canvas_obj.setFillColor(_tc('#94a3b8'))
        canvas_obj.drawRightString(W_page-MR, 8*mm, f'Página {doc_obj.page}')

        canvas_obj.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR,
        topMargin=20*mm,
        bottomMargin=18*mm
    )

    story = []

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

    # ── Construção modular das seções
    story.extend(_build_header_section(logo_bytes, ipb_logo_bytes, org_data, fiscal_year, W))
    story.extend(_build_general_data_section(org_data, fiscal_year, W, section_hdr))
    if board_data:
        story.extend(_build_board_section(board_data, W, section_hdr))
    if act_secs_data:
        story.extend(_build_secretaries_section(act_secs_data, W, section_hdr))

    story.append(PageBreak())
    story.extend(_build_intro_section(report, W, TC, section_bar_num))

    story.append(PageBreak())
    story.extend(_build_activities_list_section(activities, W, TC, section_bar_num))

    story.append(PageBreak())
    story.extend(_build_raio_x_section(report, W, TC, section_bar_num))

    story.extend(_build_activity_photos_section(activities, b2, bucket, W, TC, image_cache, section_bar_num))
    story.extend(_build_final_word_section(report, board_data, org_data, fiscal_year, W, TC, section_bar_num))

    t_story = time.perf_counter()

    doc.build(story,
        onFirstPage=_make_header_footer,
        onLaterPages=_make_header_footer,
    )
    t_end = time.perf_counter()

    image_cache.clear()
    gc.collect()

    logger.info(
        "Relatório de Atividades PDF gerado em %.2fs | "
        "Fotos: %d preparadas em %.2fs | Montagem PDF: %.2fs",
        (t_end - t_start), photo_count, (t_photos - t_start), (t_end - t_story)
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
    gc.collect()
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
                        img_bytes = _resize_image(img_bytes, max_width=900)
                        pil = _PILImage.open(io.BytesIO(img_bytes))
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
    logo_bytes: bytes = None,
    ipb_logo_bytes: bytes = None,
) -> bytes:
    """Gera o Relatório de Estatística exatamente no modelo oficial CNHP"""

    buf = io.BytesIO()
    ML = MR = 12 * mm
    W  = A4[0] - ML - MR

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=12 * mm, bottomMargin=12 * mm)

    # ── Cores exatas do modelo ──────────────────────────────
    YELLOW     = colors.HexColor('#FFC000')   # amarelo cabeçalhos
    YELLOW_ROW = colors.HexColor('#FFE699')   # amarelo linhas alternadas
    BLUE_HDR   = colors.HexColor('#1F3864')   # azul escuro cabeçalhos seção
    BLUE_LT    = colors.HexColor('#BDD7EE')   # azul claro linhas seção
    WHITE      = colors.white
    BLACK      = colors.black
    DARK       = colors.HexColor('#1a1a1a')

    GREEN_SECTION  = colors.HexColor('#C6E0B4')  # itens 1-5 (UPH local)
    BLUE_SECTION   = colors.HexColor('#DDEEFF')  # itens 6-7 (federação)
    PINK_SECTION   = colors.HexColor('#FCE4D6')  # itens 8-9 (sinodal)
    PURPLE_SECTION = colors.HexColor('#EAD1DC')  # itens 10-11 (nacional)

    ITEM_BG = {
        1: GREEN_SECTION,  2: GREEN_SECTION,
        3: GREEN_SECTION,  4: GREEN_SECTION,
        5: GREEN_SECTION,
        6: BLUE_SECTION,   7: BLUE_SECTION,
        8: PINK_SECTION,   9: PINK_SECTION,
        10: PURPLE_SECTION, 11: PURPLE_SECTION,
    }

    SECTION_COLORS = {
        1: colors.HexColor('#375623'),
        2: colors.HexColor('#1F3864'),
        3: colors.HexColor('#843C0C'),
        4: colors.HexColor('#4B1D8E'),
    }

    SECTION_BG = {
        1: GREEN_SECTION,
        2: BLUE_SECTION,
        3: PINK_SECTION,
        4: PURPLE_SECTION,
    }

    story = []

    def _p(txt, size=8.5, color=BLACK, bold=False, align=TA_LEFT,
           italic=False, leading=None):
        font = 'Helvetica-BoldOblique' if bold and italic else \
               'Helvetica-Bold' if bold else \
               'Helvetica-Oblique' if italic else 'Helvetica'
        return Paragraph(str(txt or ''), ParagraphStyle('_',
            fontSize=size, textColor=color, fontName=font,
            alignment=align,
            leading=leading or max(size * 1.35, 10),
            wordWrap='LTR', spaceAfter=0, spaceBefore=0,
        ))

    # ── Cabeçalho com logos ──────────────────────────────────
    LOGO_W   = 28 * mm
    LOGO_H   = 28 * mm
    CENTER_W = W - 2 * LOGO_W

    uph_logo_cell = _p('UPH', 10, BLUE_HDR, bold=True, align=TA_CENTER)
    if logo_bytes:
        try:
            uph_logo_cell = Image(io.BytesIO(logo_bytes), width=LOGO_W, height=LOGO_H)
        except Exception:
            pass

    ipb_logo_cell = _p('IPB', 10, BLUE_HDR, bold=True, align=TA_CENTER)
    if ipb_logo_bytes:
        try:
            ipb_logo_cell = Image(io.BytesIO(ipb_logo_bytes), width=LOGO_W, height=LOGO_H)
        except Exception:
            pass

    center_block = Table([
        [_p('CONFEDERAÇÃO NACIONAL DE', 11, BLUE_HDR, bold=True, align=TA_CENTER)],
        [_p('HOMENS PRESBITERIANOS - CNHP', 11, BLUE_HDR, bold=True, align=TA_CENTER)],
        [Spacer(1, 3 * mm)],
        [_p('RELATÓRIO DE ESTATÍSTICA', 13, BLUE_HDR, bold=True, align=TA_CENTER)],
    ], colWidths=[CENTER_W])
    center_block.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
    ]))

    hdr_t = Table(
        [[uph_logo_cell, center_block, ipb_logo_cell]],
        colWidths=[LOGO_W, CENTER_W, LOGO_W]
    )
    hdr_t.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 1.5, BLACK),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, BLACK),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',         (0, 0), (0, 0),  'CENTER'),
        ('ALIGN',         (2, 0), (2, 0),  'CENTER'),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
    ]))
    story.append(hdr_t)

    # ── Linha UPH/FEDERAÇÃO/CONF + ANO ──────────────────────
    ANO_W   = 50 * mm
    row_nivel = Table([[
        _p('UPH, FEDERAÇÃO, CONFEDERAÇÃO SINODAL,\nCONFEDERAÇÃO NACIONAL',
           9, DARK, bold=True, align=TA_CENTER),
        _p('ANO', 8, DARK, bold=True, align=TA_CENTER),
        _p(str(fiscal_year), 9, BLACK, bold=True, align=TA_CENTER),
    ]], colWidths=[W - 50*mm, 18*mm, 32*mm])
    row_nivel.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 1, BLACK),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, BLACK),
        ('BACKGROUND',    (0, 0), (0, 0),   YELLOW),
        ('BACKGROUND',    (1, 0), (1, 0),   YELLOW),
        ('BACKGROUND',    (2, 0), (2, 0),   WHITE),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
    ]))
    story.append(row_nivel)

    # ── Seções de identificação ──────────────────────────────
    is_fed   = org_data.get('organization_type') == 'federation'
    org_name = org_data.get('name', '')
    fed_name = org_data.get('federation_name', '') if not is_fed else org_name
    syn_name = org_data.get('synodal_name', '')

    def id_section_hdr(num, txt):
        bg_color = SECTION_COLORS.get(num, BLUE_HDR)
        t = Table([[
            _p(f'{num})  {txt}', 8, WHITE, bold=True, align=TA_CENTER)
        ]], colWidths=[W])
        t.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.5, BLACK),
            ('BACKGROUND',    (0, 0), (-1, -1), bg_color),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        return t

    def id_section_row(num, label, value):
        bg_color = SECTION_BG.get(num, BLUE_LT)
        t = Table([[
            _p(label, 8, DARK, bold=True),
            _p(f'  {value}', 8, BLACK),
        ]], colWidths=[80 * mm, W - 80 * mm])
        t.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.5, BLACK),
            ('INNERGRID',     (0, 0), (-1, -1), 0.5, BLACK),
            ('BACKGROUND',    (0, 0), (0, 0),   bg_color),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ]))
        return t

    story.append(id_section_hdr(1, 'UPH (ENVIAR À FEDERAÇÃO)'))
    story.append(id_section_row(1, 'NOME DA UPH: --->', org_name if not is_fed else ''))
    story.append(id_section_hdr(2, 'FEDERAÇÃO PARA A CONFEDERAÇÃO SINODAL'))
    story.append(id_section_row(2, 'NOME E SIGLA DA FEDERAÇÃO: --->', fed_name))
    story.append(id_section_hdr(3, 'CONFEDERAÇÃO SINODAL PARA A CONFEDERAÇÃO NACIONAL'))
    story.append(id_section_row(3, 'NOME E SIGLA DA CONFED. SINODAL --->', syn_name))
    sec4 = Table([[
        _p('4)  CONFEDERAÇÃO NACIONAL. ATUALIZADO EM --->',
           8, WHITE, bold=True, align=TA_LEFT),
        _p('', 8, BLACK),
    ]], colWidths=[W - 45*mm, 45*mm])
    sec4.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 0.5, BLACK),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, BLACK),
        ('BACKGROUND',    (0, 0), (0, 0),   SECTION_COLORS.get(4, BLUE_HDR)),
        ('BACKGROUND',    (1, 0), (1, 0),   WHITE),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
    ]))
    story.append(sec4)

    # ── Cabeçalho da tabela de itens ────────────────────────
    CW = [W * 0.44, W * 0.135, W * 0.135, W * 0.145, W * 0.145]

    thead = Table([[
        _p('ITEM',                  8,   BLACK, bold=True, align=TA_CENTER),
        _p('QUANT.\nANO\nATUAL',    7.5, BLACK, bold=True, align=TA_CENTER),
        _p('Δ% ANO\nATUAL',         7.5, BLACK, bold=True, align=TA_CENTER),
        _p('QUANT.\nANO\nANTERIOR', 7.5, BLACK, bold=True, align=TA_CENTER),
        _p('Δ%\nVARIAÇÃO',          7.5, BLACK, bold=True, align=TA_CENTER),
    ]], colWidths=CW)
    thead.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 0.8, BLACK),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, BLACK),
        ('BACKGROUND',    (0, 0), (-1, -1), YELLOW),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
    ]))
    story.append(thead)

    # ── Itens da tabela ──────────────────────────────────────
    items_def = [
        (1,  'Quantidade de Homens na igreja',           None,  False),
        (2,  'Quantidade de Homens na UPH',              None, False),
        (3,  'Quantidade de Oficiais na igreja',         None,  False),
        (4,  'Quantidade de Oficiais sócios da UPH',    None,  False),
        (5,  'Quantidade de Congregações',               None,  False),
        (6,  'Quantidade de Igrejas',                    None,  True),
        (7,  'Quantidade de UPHs',                       None, True),
        (8,  'Quantidade de Presbitérios',               None,  True),
        (9,  'Quantidade de Federações',                 None,  True),
        (10, 'Quantidade de Sínodos',                    None,  True),
        (11, 'Quantidade de Confederações Sinodais',     None,  True),
    ]

    def fmt_num(n):
        return str(n) if n else ''

    def fmt_dlt(d, prev):
        if d is None or prev == 0:
            return ''
        sign = '+' if d > 0 else ''
        return f'{sign}{d:.1f}%'

    def _rel_pct(num, den):
        if not den or den == 0:
            return None
        return round((num / den) * 100, 1)

    def make_pair_rows(item_a, item_b, rel_value, items_def, stat, CW):
        def get_item_data(num):
            for n, desc, nota, _ in items_def:
                if n == num:
                    cur  = stat.get(f'item{num}_current',  0) or 0
                    prev = stat.get(f'item{num}_previous', 0) or 0
                    dlt  = stat.get(f'item{num}_delta')
                    return desc, nota, cur, prev, dlt
            return '', None, 0, 0, None

        desc_a, nota_a, cur_a, prev_a, dlt_a = get_item_data(item_a)
        desc_b, nota_b, cur_b, prev_b, dlt_b = get_item_data(item_b)

        bg_a = ITEM_BG.get(item_a, WHITE)
        bg_b = ITEM_BG.get(item_b, WHITE)

        def make_desc_para(num, desc, nota):
            txt = f'{num}. {desc}&nbsp;&nbsp;<b>{nota}</b>' if nota else f'{num}. {desc}'
            return Paragraph(txt, ParagraphStyle('item', fontSize=8.5, textColor=BLACK,
                                                  fontName='Helvetica', leading=11,
                                                  leftIndent=3, spaceAfter=0, spaceBefore=0))

        def _dlt_color(s):
            if not s: return BLACK
            return colors.HexColor('#166534') if not s.startswith('-') \
                   else colors.HexColor('#991b1b')

        rel_str   = f'{rel_value:.1f}%' if rel_value is not None else ''
        dlt_str_a = fmt_dlt(dlt_a, prev_a)
        dlt_str_b = fmt_dlt(dlt_b, prev_b)

        pair_data = [
            [
                make_desc_para(item_a, desc_a, nota_a),
                _p(fmt_num(cur_a)  if cur_a  else '', 8.5, BLACK, align=TA_CENTER),
                _p(rel_str, 8.5, BLACK, bold=bool(rel_str), align=TA_CENTER),
                _p(fmt_num(prev_a) if prev_a else '', 8.5, BLACK, align=TA_CENTER),
                _p(dlt_str_a, 8.5, _dlt_color(dlt_str_a), bold=bool(dlt_str_a), align=TA_CENTER),
            ],
            [
                make_desc_para(item_b, desc_b, nota_b),
                _p(fmt_num(cur_b)  if cur_b  else '', 8.5, BLACK, align=TA_CENTER),
                _p('', 8.5, BLACK, align=TA_CENTER),
                _p(fmt_num(prev_b) if prev_b else '', 8.5, BLACK, align=TA_CENTER),
                _p(dlt_str_b, 8.5, _dlt_color(dlt_str_b), bold=bool(dlt_str_b), align=TA_CENTER),
            ],
        ]

        pair_t = Table(pair_data, colWidths=CW)
        pair_t.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.5, BLACK),
            ('INNERGRID',     (0, 0), (-1, -1), 0.5, BLACK),
            ('SPAN',          (2, 0), (2, 1)),
            ('VALIGN',        (2, 0), (2, 1), 'MIDDLE'),
            ('ALIGN',         (2, 0), (2, 1), 'CENTER'),
            ('BACKGROUND',    (0, 0), (-1, 0), bg_a),
            ('BACKGROUND',    (0, 1), (-1, 1), bg_b),
            ('BACKGROUND',    (2, 0), (2, 1), bg_a),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',   (0, 0), (-1, -1), 3),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ]))
        return pair_t

    rel_1_2 = _rel_pct(stat.get('item2_current', 0) or 0, stat.get('item1_current', 0) or 0)
    rel_3_4 = _rel_pct(stat.get('item4_current', 0) or 0, stat.get('item3_current', 0) or 0)
    rel_6_7 = _rel_pct(stat.get('item7_current', 0) or 0, stat.get('item6_current', 0) or 0)

    story.append(make_pair_rows(1, 2, rel_1_2, items_def, stat, CW))
    story.append(make_pair_rows(3, 4, rel_3_4, items_def, stat, CW))

    # Item 5 avulso
    for num, desc, nota, _ in items_def:
        if num != 5:
            continue
        cur  = stat.get('item5_current',  0) or 0
        prev = stat.get('item5_previous', 0) or 0
        dlt  = stat.get('item5_delta')
        dlt_str = fmt_dlt(dlt, prev)
        dlt_color_5 = BLACK
        if dlt_str:
            dlt_color_5 = colors.HexColor('#166534') if not dlt_str.startswith('-') \
                          else colors.HexColor('#991b1b')
        desc_para = Paragraph(
            f'5. {desc}&nbsp;&nbsp;<b>{nota}</b>' if nota else f'5. {desc}',
            ParagraphStyle('item', fontSize=8.5, textColor=BLACK,
                           fontName='Helvetica', leading=11,
                           leftIndent=3, spaceAfter=0, spaceBefore=0)
        )
        row5 = Table([[
            desc_para,
            _p(fmt_num(cur)  if cur  else '', 8.5, BLACK, align=TA_CENTER),
            _p('', 8.5, BLACK, align=TA_CENTER),
            _p(fmt_num(prev) if prev else '', 8.5, BLACK, align=TA_CENTER),
            _p(dlt_str, 8.5, dlt_color_5, bold=bool(dlt_str), align=TA_CENTER),
        ]], colWidths=CW)
        row5.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.5, BLACK),
            ('INNERGRID',     (0, 0), (-1, -1), 0.5, BLACK),
            ('BACKGROUND',    (0, 0), (-1, -1), ITEM_BG.get(5, GREEN_SECTION)),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',   (0, 0), (-1, -1), 3),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ]))
        story.append(row5)

    story.append(make_pair_rows(6, 7, rel_6_7, items_def, stat, CW))
    story.append(make_pair_rows(8, 9,  None,   items_def, stat, CW))
    story.append(make_pair_rows(10, 11, None,  items_def, stat, CW))

    # ── Bloco de orientações ─────────────────────────────────
    story.append(Spacer(1, 1.5 * mm))

    def orient_row(txt, bg, text_color=BLACK, bold=False, italic=False,
                   size=8, align=TA_CENTER, link=False):
        font_name = 'Helvetica-Bold' if bold else \
                    'Helvetica-Oblique' if italic else 'Helvetica'
        if link:
            content = Paragraph(
                f'<u><font color="#0070C0">{txt}</font></u>',
                ParagraphStyle('_', fontSize=size, fontName=font_name,
                               alignment=align, leading=size * 1.4,
                               spaceAfter=0, spaceBefore=0)
            )
        else:
            content = Paragraph(
                txt,
                ParagraphStyle('_', fontSize=size, textColor=text_color,
                               fontName=font_name, alignment=align,
                               leading=size * 1.4, spaceAfter=0, spaceBefore=0)
            )
        t = Table([[content]], colWidths=[W])
        t.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.3, BLACK),
            ('BACKGROUND',    (0, 0), (-1, -1), bg),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
        ]))
        return t

    story.append(orient_row(
        'PREENCHIMENTO, ENCAMINHAMENTO, ORIENTAÇÕES',
        YELLOW, BLACK, bold=True, size=8.5
    ))
    story.append(orient_row(
        '(NÃO PREENCHER À MÃO)',
        YELLOW, BLACK, bold=True, size=8.5
    ))
    story.append(orient_row(
        '1) A UPH preenche os itens 1 a 5 e informa à Federação',
        GREEN_SECTION, BLACK, size=8
    ))
    story.append(orient_row(
        '2) A Federação soma os itens 1 a 5 dos relatórios das UPHs, transcreve, '
        'preenche os itens 6 e 7 e informa à Confederação Sinodal',
        BLUE_SECTION, BLACK, size=8
    ))
    story.append(orient_row(
        '3) A Sinodal soma os itens 1 a 7 dos relatórios das Federações, transcreve, '
        'preenche os itens 8 e 9 e informa à Confederação Nacional',
        PINK_SECTION, BLACK, size=8
    ))
    story.append(orient_row(
        '4) A CNHP, através da Sec. de Estatística, soma os itens 1 a 9, transcreve, '
        'preenche os 10 e 11 e informa às Confederações Sinodais, estas às Federações, '
        'e estas às UPHs',
        PURPLE_SECTION, BLACK, size=8
    ))
    story.append(orient_row(
        'Veja no site da CNHP: Cem Oportunidades para a UPH - www.uph.org.br',
        WHITE, BLACK, size=8, link=True
    ))
    story.append(orient_row(
        'Utilize as Cem Oportunidades no planejamento de atividades da UPH, Federação e '
        'Confederação e não deixe de informar no Formulário Padrão de Atividades que foram realizados.',
        YELLOW_ROW, BLACK, size=8
    ))
    story.append(orient_row(
        'Acesse o Formulário Padronizado de Atividades da UPH no site da Secretaria Executiva',
        WHITE, BLACK, size=8, link=True
    ))
    story.append(orient_row(
        '"Portanto, meus amados irmãos, sede firmes e sempre abundantes na obra do Senhor, '
        'sabendo que, no Senhor, o vosso trabalho não é vão". (I Co 15.58)',
        YELLOW_ROW, BLACK, italic=True, size=7.5
    ))

    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════
# RELATÓRIO DE ELEIÇÕES
# ═══════════════════════════════════════════════════════════════

def generate_election_report(
    election_data: dict,
    org_data: dict,
    logo_bytes: bytes = None,
    ipb_logo_bytes: bytes = None,
    theme_color: str = '#1a2a6c',
) -> bytes:
    """Gera o PDF com o histórico e apuração completa dos escrutínios da eleição."""
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
        [Spacer(1, 1 * mm)],
        [Paragraph('RELATÓRIO OFICIAL DE PROCESSO ELEITORAL', _ps(11, TC, bold=True, align=TA_CENTER))],
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
    story.append(HRFlowable(width=W, thickness=1.5, color=TC))
    story.append(Spacer(1, 3 * mm))

    # ── Identificação da Eleição ──────────────────────────────
    ident_data = [
        [Paragraph('<b>Eleição:</b>', _ps(8.5, BLACK)), Paragraph(election_data.get('title', '—'), _ps(8.5, BLACK))],
        [Paragraph('<b>Data de Apuração:</b>', _ps(8.5, BLACK)), Paragraph(_fd(election_data.get('created_at', '—')), _ps(8.5, BLACK))],
        [Paragraph('<b>Status:</b>', _ps(8.5, BLACK)), Paragraph('CONCLUÍDA' if election_data.get('status') == 'completed' else 'EM ANDAMENTO', _ps(8.5, BLACK, bold=True))],
    ]
    ident_table = Table(ident_data, colWidths=[40 * mm, W - 40 * mm])
    ident_table.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
    ]))
    story.append(ident_table)
    story.append(Spacer(1, 4 * mm))

    # ── Diretoria Eleita ─────────────────────────────────────
    story.append(_section_bar('DIRETORIA ELEITA', W, TC))
    story.append(Spacer(1, 2 * mm))

    dir_rows = []
    ROLE_LABELS = {
        'presidente': 'Presidente',
        'vice_presidente': 'Vice-Presidente',
        '1_secretario': '1º Secretário(a)',
        '2_secretario': '2º Secretário(a)',
        'secretario_executivo': 'Secretário Executivo',
        'tesoureiro': 'Tesoureiro(a)',
    }
    
    elected_positions = election_data.get('elected_positions') or {}
    if not elected_positions:
        dir_rows.append([Paragraph('Nenhum cargo foi concluído ainda.', _ps(9, GRAY_TXT, italic=True))])
    else:
        for role_key, name in elected_positions.items():
            role_label = ROLE_LABELS.get(role_key, role_key.replace('_', ' ').title())
            dir_rows.append([
                Paragraph(f'<b>{role_label}:</b>', _ps(9, BLACK)),
                Paragraph(name or '—', _ps(9, BLACK, bold=True))
            ])
            
    dir_table = Table(dir_rows, colWidths=[50 * mm, W - 50 * mm] if elected_positions else [W])
    dir_table.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX',           (0, 0), (-1, -1), 0.5, GRAY_LINE),
    ]))
    story.append(dir_table)
    story.append(Spacer(1, 6 * mm))

    # ── Detalhes por Cargo e Escrutínio ───────────────────────
    story.append(_section_bar('DETALHAMENTO DOS VOTOS POR ESCRUTÍNIO', W, TC))
    story.append(Spacer(1, 3 * mm))

    roles_disputed = election_data.get('roles_disputed') or []
    for role_item in roles_disputed:
        role_label = role_item.get('role_label', '')
        winner_name = role_item.get('winner_name')
        story.append(Paragraph(f'<b>Cargo: {role_label.upper()}</b>', _ps(10, TC, bold=True)))
        story.append(Spacer(1, 1.5 * mm))

        for r_item in role_item.get('rounds', []):
            round_num = r_item.get('round', 1)
            total_votes = r_item.get('total_votes', 0)
            story.append(Paragraph(f'• {round_num}º Escrutínio (Total de Votos: {total_votes})', _ps(9, BLACK, bold=True)))
            story.append(Spacer(1, 1 * mm))

            # Table for results in this round
            table_data = [[
                Paragraph('<b>Candidato</b>', _ps(8, BLACK, bold=True)),
                Paragraph('<b>Votos</b>', _ps(8, BLACK, bold=True, align=TA_CENTER)),
                Paragraph('<b>Porcentagem</b>', _ps(8, BLACK, bold=True, align=TA_RIGHT))
            ]]

            for res in r_item.get('results', []):
                pct_str = f"{res.get('percentage', 0):.1f}%"
                table_data.append([
                    Paragraph(res.get('name', ''), _ps(8, BLACK)),
                    Paragraph(str(res.get('votes', 0)), _ps(8, BLACK, align=TA_CENTER)),
                    Paragraph(pct_str, _ps(8, BLACK, align=TA_RIGHT))
                ])

            round_table = Table(table_data, colWidths=[W - 60 * mm, 30 * mm, 30 * mm])
            round_table.setStyle(TableStyle([
                ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID',          (0, 0), (-1, -1), 0.5, GRAY_LINE),
                ('BACKGROUND',    (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
                ('TOPPADDING',    (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(round_table)
            story.append(Spacer(1, 3 * mm))

        if winner_name:
            story.append(Paragraph(f'<i>Resultado: <b>{winner_name}</b> foi eleito(a) para o cargo de {role_label}.</i>', _ps(8.5, GREEN)))
        else:
            story.append(Paragraph(f'<i>Resultado: Cargo não concluído ou sem eleito.</i>', _ps(8.5, RED_C)))
            
        story.append(Spacer(1, 5 * mm))
        story.append(HRFlowable(width=W, thickness=0.5, color=GRAY_LINE))
        story.append(Spacer(1, 3 * mm))

    # ── Assinaturas da Mesa Eleitoral ─────────────────────────
    story.append(Spacer(1, 8 * mm))
    sig_data = [
        [
            Paragraph('__________________________________________<br/>Presidente da Assembleia', _ps(8.5, BLACK, align=TA_CENTER)),
            Paragraph('__________________________________________<br/>Secretário(a) da Assembleia', _ps(8.5, BLACK, align=TA_CENTER))
        ]
    ]
    sig_table = Table(sig_data, colWidths=[W/2, W/2])
    sig_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(sig_table)

    doc.build(story)
    return buf.getvalue()