import datetime
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.election import ElectionSession, ElectionVote, ElectionVoter
from app.models.member import Member

MONTHS_PT = [
    '', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
    'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'
]

ROLE_LABELS = {
    'presidente': 'Presidente',
    'vice_presidente': 'Vice-Presidente',
    '1_secretario': '1º Secretário(a)',
    '2_secretario': '2º Secretário(a)',
    'secretario_executivo': 'Secretário Executivo',
    'tesoureiro': 'Tesoureiro(a)',
}

def format_date_pt(dt: datetime.datetime or datetime.date) -> str:
    if not dt:
        return "—"
    try:
        day = dt.day
        month_name = MONTHS_PT[dt.month]
        year = dt.year
        return f"{day} de {month_name} de {year}"
    except Exception:
        return str(dt).split("T")[0]


def build_minutes_data(db: Session, session: ElectionSession) -> dict:
    """Extrai e consolida todos os dados do processo eleitoral para a lavratura da Ata."""
    # 1. Diretoria Eleita
    elected_positions_names = {}
    elected_positions = session.elected_positions or {}
    for role_key, member_id in elected_positions.items():
        try:
            m = db.query(Member).filter(Member.id == UUID(str(member_id))).first()
            elected_positions_names[role_key] = m.full_name if m else "Desconhecido"
        except Exception:
            elected_positions_names[role_key] = "Desconhecido"

    # 2. Quórum Inicial e Final
    voters = db.query(ElectionVoter).filter(
        ElectionVoter.election_session_id == session.id
    ).all()
    final_voters_count = len(voters)
    final_votable_count = sum(1 for v in voters if v.can_be_voted)

    removed_voters = list(session.removed_voters or [])
    initial_voters_count = session.initial_voters_count or (final_voters_count + len(removed_voters))
    initial_votable_count = session.initial_votable_count or final_votable_count

    # 3. Histórico de Declínios
    declines = []
    if session.decline_history:
        declines = list(session.decline_history)
    elif session.declined_candidates:
        # Reconstruct from declined_candidates JSON map if older session
        for role_key, m_ids in (session.declined_candidates or {}).items():
            for mid in m_ids:
                try:
                    m = db.query(Member).filter(Member.id == UUID(str(mid))).first()
                    m_name = m.full_name if m else "Desconhecido"
                except Exception:
                    m_name = "Desconhecido"
                declines.append({
                    "member_id": str(mid),
                    "member_name": m_name,
                    "role": role_key,
                    "role_label": ROLE_LABELS.get(role_key, role_key.replace('_', ' ').title()),
                    "round": 1,
                    "was_elected": False,
                })

    # 4. Apuração dos Escrutínios e Votos por Cargo
    votes = db.query(ElectionVote).filter(
        ElectionVote.election_session_id == session.id
    ).all()

    votes_map = {}
    for v in votes:
        role = v.role
        r = v.round
        cid = v.candidate_member_id
        if role not in votes_map:
            votes_map[role] = {}
        if r not in votes_map[role]:
            votes_map[role][r] = {}
        votes_map[role][r][cid] = votes_map[role][r].get(cid, 0) + 1

    roles_disputed = []
    for role in (session.roles_to_dispute or []):
        role_label = ROLE_LABELS.get(role, role.replace('_', ' ').title())
        winner_name = elected_positions_names.get(role)

        rounds_list = []
        role_votes = votes_map.get(role, {})
        for r_num in sorted(role_votes.keys()):
            r_votes = role_votes[r_num]
            total_r_votes = sum(r_votes.values())

            results_list = []
            for cid, count in r_votes.items():
                if cid is None:
                    name = "Branco/Nulo"
                    cid_str = "blank"
                else:
                    m = db.query(Member).filter(Member.id == cid).first()
                    name = m.full_name if m else "Desconhecido"
                    cid_str = str(cid)

                pct = (count / total_r_votes * 100) if total_r_votes > 0 else 0
                results_list.append({
                    "candidate_id": cid_str,
                    "name": name,
                    "votes": count,
                    "percentage": pct
                })

            results_list.sort(key=lambda x: x["votes"], reverse=True)
            rounds_list.append({
                "round": r_num,
                "total_votes": total_r_votes,
                "results": results_list
            })

        roles_disputed.append({
            "role": role,
            "role_label": role_label,
            "winner_name": winner_name,
            "rounds": rounds_list
        })

    date_formatted = format_date_pt(session.created_at) if session.created_at else "—"

    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "date_formatted": date_formatted,
        "status": session.status,
        "elected_positions": elected_positions_names,
        "initial_voters_count": initial_voters_count,
        "initial_votable_count": initial_votable_count,
        "final_voters_count": final_voters_count,
        "final_votable_count": final_votable_count,
        "removed_voters": removed_voters,
        "declines": declines,
        "roles_disputed": roles_disputed
    }


def generate_minutes_narrative_text(data: dict, org_name: str) -> str:
    """Gera a redação formal completa em prosa da Ata de Eleição (padrão IPB para Livro de Atas)."""
    title = data.get("title", "Eleição de Diretoria")
    date_str = data.get("date_formatted", "—")
    elected = data.get("elected_positions") or {}
    init_v = data.get("initial_voters_count", 0)
    init_cand = data.get("initial_votable_count", 0)
    final_v = data.get("final_voters_count", 0)
    final_cand = data.get("final_votable_count", 0)
    removed = data.get("removed_voters") or []
    declines = data.get("declines") or []
    roles = data.get("roles_disputed") or []

    lines = []
    lines.append(f"ATA DA ASSEMBLEIA GERAL ORDINÁRIA DE ELEIÇÃO DA DIRETORIA")
    lines.append(f"{org_name.upper()} — IGREJA PRESBITERIANA DO BRASIL")
    lines.append(f"PROCESSO ELEITORAL: {title.upper()}")
    lines.append(f"DATA DO PLEITO: {date_str}\n")
    lines.append("=" * 70)
    lines.append("I. DIRETORIA ELEITA")
    lines.append("=" * 70)
    if not elected:
        lines.append("Nenhum cargo foi concluído nesta sessão.")
    else:
        for r_key, name in elected.items():
            r_label = ROLE_LABELS.get(r_key, r_key.replace('_', ' ').title())
            lines.append(f"• {r_label}: {name}")
    lines.append("")

    lines.append("=" * 70)
    lines.append("II. INSTALAÇÃO, ABERTURA E VERIFICAÇÃO DE QUÓRUM")
    lines.append("=" * 70)
    p1 = (
        f"Aos {date_str}, sob a invocação da graça de Deus, reuniu-se a Assembleia Geral da "
        f"{org_name} para a realização da eleição de sua Diretoria. "
        f"Instalada a mesa diretora dos trabalhos, realizou-se a verificação do quórum de membros, "
        f"registrando-se no início da assembleia a presença de {init_v} membros votantes credenciados, "
        f"dentre os quais {init_cand} membros em condições estatutárias de elegibilidade (votáveis). "
        f"Ficou consignado em plenário o cumprimento das normas constitucionais regimentais: "
        f"exigência de maioria absoluta dos votos do quórum para eleição no 1º e 2º escrutínios, "
        f"e maioria simples no 3º escrutínio."
    )
    lines.append(p1 + "\n")

    lines.append("=" * 70)
    lines.append("III. OCORRÊNCIAS DE QUÓRUM E REMOÇÕES")
    lines.append("=" * 70)
    if removed:
        names_rem = ", ".join([r.get("member_name", "Membro") for r in removed])
        p2 = (
            f"Durante o transcurso da sessão, registrou-se a remoção de {len(removed)} eleitor(es) "
            f"do quórum por ausência em plenário: {names_rem}. O quórum foi formalmente ajustado, "
            f"consolidando-se a assembleia com {final_v} membros votantes e {final_cand} membros votáveis."
        )
    else:
        p2 = (
            f"Não houve remoção de eleitores durante a assembleia, permanecendo o quórum final inalterado "
            f"com {final_v} membros votantes e {final_cand} membros votáveis."
        )
    lines.append(p2 + "\n")

    lines.append("=" * 70)
    lines.append("IV. REGISTRO DE DECLÍNIOS DE CANDIDATURA")
    lines.append("=" * 70)
    if declines:
        lines.append("Foram registradas em plenário as seguintes manifestações de declínio de candidatura:")
        for d in declines:
            m_name = d.get("member_name", "—")
            r_label = d.get("role_label", d.get("role", "—"))
            rnd = d.get("round", 1)
            was_el = d.get("was_elected", False)
            if was_el:
                lines.append(
                    f"• {m_name}: declinou do cargo de {r_label} após haver obtido a maioria (proclamação revogada; "
                    f"o pleito seguiu para o escrutínio seguinte sem este candidato, com quórum mantido e garantido "
                    f"seu direito de voto e elegibilidade nos cargos posteriores)."
                )
            else:
                lines.append(
                    f"• {m_name}: declinou da disputa para o cargo de {r_label} no {rnd}º escrutínio "
                    f"(retirado da votação deste cargo, mantendo seu direito a voto e elegibilidade nos cargos seguintes)."
                )
    else:
        lines.append("Não houve manifestação de declínio de candidatura durante o processo eleitoral.")
    lines.append("")

    lines.append("=" * 70)
    lines.append("V. RELATÓRIO PORMENORIZADO DOS ESCRUTÍNIOS POR CARGO")
    lines.append("=" * 70)
    for idx, r in enumerate(roles, 1):
        r_label = r.get("role_label", "")
        winner = r.get("winner_name")
        lines.append(f"{idx}. ELEIÇÃO PARA O CARGO DE {r_label.upper()}")
        
        rounds = r.get("rounds", [])
        for rnd in rounds:
            r_num = rnd.get("round", 1)
            tot = rnd.get("total_votes", 0)
            maj_text = f"{(tot // 2) + 1} votos" if r_num in (1, 2) else "Mais votado"
            lines.append(f"   • {r_num}º Escrutínio — Total de Votos: {tot} | Maioria Exigida: {maj_text}")
            for c in rnd.get("results", []):
                lines.append(f"     - {c.get('name')}: {c.get('votes')} voto(s) ({c.get('percentage', 0):.1f}%)")
        
        if winner:
            lines.append(f"   Desfecho: Solenemente proclamado(a) eleito(a) para {r_label}: {winner}.\n")
        else:
            lines.append(f"   Desfecho: Cargo sem eleito proclamado ou não concluído.\n")

    lines.append("=" * 70)
    lines.append("VI. ENCERRAMENTO E ASSINATURAS")
    lines.append("=" * 70)
    closure = (
        "Esgotada a pauta de votações e apurados todos os cargos da Diretoria, o Presidente proclamou "
        "oficialmente os eleitos para o exercício regimental. Nada mais havendo a tratar, encerrou-se a reunião com oração. "
        "E, para constar, eu, Secretário(a), lavrei a presente ata que, lida e aprovada pela assembleia, "
        "vai assinada pela Mesa Diretora e Comissão Escrutinadora.\n\n"
        "________________________________________         ________________________________________\n"
        "        Presidente da Assembleia                         Secretário(a) da Assembleia\n\n"
        "________________________________________         ________________________________________\n"
        "           1º Escrutinador(a)                               2º Escrutinador(a)"
    )
    lines.append(closure)

    return "\n".join(lines)


def generate_minutes_doc_html(minutes_data: dict, org_name: str, theme_color: str = '#1a2a6c') -> str:
    """Gera o arquivo HTML estruturado compatível nativamente com Microsoft Word (.doc)."""
    title = minutes_data.get("title", "Eleição de Diretoria")
    date_str = minutes_data.get("date_formatted", "—")
    elected = minutes_data.get("elected_positions") or {}
    init_v = minutes_data.get("initial_voters_count", 0)
    init_cand = minutes_data.get("initial_votable_count", 0)
    final_v = minutes_data.get("final_voters_count", 0)
    final_cand = minutes_data.get("final_votable_count", 0)
    removed = minutes_data.get("removed_voters") or []
    declines = minutes_data.get("declines") or []
    roles = minutes_data.get("roles_disputed") or []

    # Elected rows HTML
    elected_rows = ""
    for r_key, name in elected.items():
        r_label = ROLE_LABELS.get(r_key, r_key.replace('_', ' ').title())
        elected_rows += f"<tr><td style='padding:6px 10px;font-weight:bold;width:200px;'>{r_label}</td><td style='padding:6px 10px;'>{name}</td></tr>"

    # Declines HTML
    declines_html = ""
    if declines:
        declines_html = "<table border='1' cellspacing='0' cellpadding='5' style='border-collapse:collapse;width:100%;margin-top:8px;font-size:10pt;border-color:#fecaca;'><tr style='background:#fee2e2;'><th>Membro</th><th>Cargo</th><th>Escrutínio</th><th>Condição / Desfecho</th></tr>"
        for d in declines:
            m_name = d.get("member_name", "—")
            r_label = d.get("role_label", d.get("role", "—"))
            rnd = d.get("round", 1)
            was_el = d.get("was_elected", False)
            status_text = "Declinou após eleito(a) (proclamação revogada; avançou para próximo escrutínio sem este concorrente)" if was_el else "Declinou da disputa (retirado da votação deste cargo; manteve direito a voto e elegibilidade nos cargos seguintes)"
            declines_html += f"<tr><td><b>{m_name}</b></td><td>{r_label}</td><td align='center'>{rnd}º</td><td>{status_text}</td></tr>"
        declines_html += "</table>"
    else:
        declines_html = "<p style='font-style:italic;color:#666;'>Não houve manifestação de declínio de candidatura durante o processo eleitoral.</p>"

    # Removed voters HTML
    removed_html = ""
    if removed:
        names_rem = ", ".join([r.get("member_name", "Membro") for r in removed])
        removed_html = f"<p style='color:#b91c1c;margin:6px 0;'><b>Eleitores Removidos por Ausência em Plenário:</b> {names_rem} ({len(removed)} membro(s) removido(s) para ajuste de quórum regimental).</p>"
    else:
        removed_html = "<p style='color:#666;margin:6px 0;'>Não houve remoção de eleitores durante a sessão eleitoral.</p>"

    # Roles and rounds HTML
    roles_html = ""
    for idx, r in enumerate(roles, 1):
        r_label = r.get("role_label", "")
        winner = r.get("winner_name")
        roles_html += f"<h4 style='color:{theme_color};margin-top:16px;margin-bottom:6px;'>{idx}. Eleição para o Cargo de {r_label.upper()}</h4>"

        for rnd in r.get("rounds", []):
            r_num = rnd.get("round", 1)
            tot = rnd.get("total_votes", 0)
            maj_text = f"{(tot // 2) + 1} votos" if r_num in (1, 2) else "Mais votado"
            roles_html += f"<p style='font-size:10pt;font-weight:bold;margin:4px 0;'>• {r_num}º Escrutínio (Total de votos apurados: {tot} | Maioria regimental: {maj_text})</p>"
            roles_html += "<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse;width:100%;margin-bottom:8px;font-size:9.5pt;border-color:#ccc;'><tr style='background:#f1f5f9;'><th align='left'>Candidato</th><th align='center' style='width:90px;'>Votos</th><th align='right' style='width:100px;'>Porcentagem</th></tr>"
            for c in rnd.get("results", []):
                roles_html += f"<tr><td>{c.get('name')}</td><td align='center'>{c.get('votes')}</td><td align='right'>{c.get('percentage', 0):.1f}%</td></tr>"
            roles_html += "</table>"

        if winner:
            roles_html += f"<p style='font-size:10pt;color:#16a34a;margin:4px 0 12px 0;'><b>Desfecho:</b> Solenemente proclamado(a) eleito(a) para {r_label}: <b>{winner}</b>.</p>"
        else:
            roles_html += f"<p style='font-size:10pt;color:#dc2626;margin:4px 0 12px 0;'><b>Desfecho:</b> Cargo não concluído ou pendente de finalização.</p>"

    html = f"""<!DOCTYPE html>
<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'>
<head>
  <meta charset='utf-8'>
  <title>Ata da Eleição - {title}</title>
  <!--[if gte mso 9]>
  <xml>
    <w:WordDocument>
      <w:View>Print</w:View>
      <w:Zoom>100</w:Zoom>
      <w:DoNotOptimizeForBrowser/>
    </w:WordDocument>
  </xml>
  <![endif]-->
  <style>
    body {{ font-family: 'Calibri', 'Arial', sans-serif; font-size: 11pt; line-height: 1.5; color: #222; margin: 2cm; }}
    h1 {{ font-size: 15pt; text-align: center; color: {theme_color}; margin-bottom: 2px; text-transform: uppercase; }}
    h2 {{ font-size: 12pt; text-align: center; color: #333; margin-top: 2px; margin-bottom: 4px; }}
    h3 {{ font-size: 11pt; text-align: center; color: #555; margin-top: 0; margin-bottom: 15px; }}
    .section-title {{ background: {theme_color}; color: #fff; padding: 5px 8px; font-size: 11pt; font-weight: bold; margin-top: 20px; margin-bottom: 10px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    p {{ margin-bottom: 8px; text-align: justify; }}
  </style>
</head>
<body>
  <h1>Igreja Presbiteriana do Brasil</h1>
  <h2>{org_name}</h2>
  <h3>ATA DA ASSEMBLEIA GERAL ORDINÁRIA DE ELEIÇÃO DA DIRETORIA</h3>
  <hr style="border: 0; border-top: 2px solid {theme_color}; margin-bottom: 15px;" />

  <div class="section-title">I. DIRETORIA ELEITA E DATA DO PLEITO</div>
  <p><b>Processo Eleitoral:</b> {title}</p>
  <p><b>Data de Realização:</b> {date_str}</p>
  <table border="1" cellpadding="6" style="border-collapse: collapse; width: 100%; margin-top: 8px; background: #f0fdf4; border-color: #bbf7d0;">
    {elected_rows}
  </table>

  <div class="section-title">II. INSTALAÇÃO, ABERTURA E QUÓRUM REGIMENTAL</div>
  <p>
    Aos {date_str}, sob a invocação da graça de Deus, reuniu-se a Assembleia Geral da {org_name}
    para a eleição de sua Diretoria para o próximo exercício. Instalada a mesa diretora, constatou-se no início dos trabalhos
    a presença de <b>{init_v} membros votantes credenciados</b>, dentre os quais <b>{init_cand} membros votáveis (elegíveis)</b>.
    Ficou consignada a observância dos preceitos estatutários: maioria absoluta dos votos do quórum para eleição no 1º e 2º escrutínios,
    e maioria simples no 3º escrutínio.
  </p>
  <p><b>Quórum Inicial:</b> {init_v} votantes | {init_cand} votáveis</p>
  <p><b>Quórum Final Consolidado:</b> {final_v} votantes | {final_cand} votáveis</p>
  {removed_html}

  <div class="section-title">III. REGISTRO DE DECLÍNIOS DE CANDIDATURA</div>
  {declines_html}

  <div class="section-title">IV. RELATÓRIO PORMENORIZADO DOS ESCRUTÍNIOS POR CARGO</div>
  {roles_html}

  <div class="section-title">V. TERMO DE ENCERRAMENTO E ASSINATURAS</div>
  <p>
    Esgotada a pauta de votações e apurados todos os cargos da Diretoria, o Presidente proclamou
    oficialmente os eleitos para o exercício regimental. Nada mais havendo a tratar, encerrou-se a assembleia com oração.
    E, para constar, eu, Secretário(a), lavrei a presente ata que, lida e achada conforme por toda a assembleia,
    vai devidamente assinada pelos membros da mesa diretora e comissão eleitoral escrutinadora.
  </p>
  <br/><br/>
  <table style="width: 100%; text-align: center; margin-top: 25px;">
    <tr>
      <td style="width: 50%; padding-bottom: 30px;">__________________________________________<br/><b>Presidente da Assembleia</b></td>
      <td style="width: 50%; padding-bottom: 30px;">__________________________________________<br/><b>Secretário(a) da Assembleia</b></td>
    </tr>
    <tr>
      <td style="width: 50%; padding-top: 20px;">__________________________________________<br/><b>1º Escrutinador(a)</b></td>
      <td style="width: 50%; padding-top: 20px;">__________________________________________<br/><b>2º Escrutinador(a)</b></td>
    </tr>
  </table>
</body>
</html>"""
    return html
