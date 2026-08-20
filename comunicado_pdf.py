"""Gera o PDF do Comunicado Individual do Programa Constelação — a versão feita pra ser entregue
ao médico (não é a mesma tela do sistema, que mostra dado interno tipo custo de seguro pago pela
empresa). Página única, reportlab puro (Platypus), sem depender de fonte/logo externos.
"""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

import core

CORES_NIVEL = {
    1: colors.HexColor("#6B7280"),
    2: colors.HexColor("#2563EB"),
    3: colors.HexColor("#7C3AED"),
    4: colors.HexColor("#B45309"),
}


def gerar_pdf_comunicado(
    nome_medico, mes_ref, nivel_vestido, n_plantoes, n_fds, n_noturno, pct_aumento_exibido,
    tempo_no_nivel=None, proximo_nivel_info=None,
):
    """Monta o PDF em memória e retorna os bytes prontos pra um st.download_button."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=2.2 * cm, bottomMargin=2 * cm, leftMargin=2.4 * cm, rightMargin=2.4 * cm,
        title=f"Comunicado Programa Constelação — {nome_medico}",
    )
    styles = getSampleStyleSheet()
    cor_texto = colors.HexColor("#1F2937")
    cor_texto_leve = colors.HexColor("#6B7280")
    cor_linha = colors.HexColor("#E5E7EB")

    titulo = ParagraphStyle(
        "TituloCallmed", parent=styles["Title"], fontSize=20, spaceAfter=2, textColor=cor_texto,
    )
    subtitulo = ParagraphStyle(
        "Subtitulo", parent=styles["Normal"], fontSize=11, textColor=cor_texto_leve, spaceAfter=16,
    )
    h2 = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontSize=13, spaceBefore=16, spaceAfter=8,
        textColor=cor_texto,
    )
    corpo = ParagraphStyle("Corpo", parent=styles["Normal"], fontSize=10.5, leading=15)
    beneficio_style = ParagraphStyle(
        "Beneficio", parent=styles["Normal"], fontSize=10.5, leading=16, leftIndent=6,
    )

    cor_nivel = CORES_NIVEL.get(int(nivel_vestido), colors.grey)
    badge_style = ParagraphStyle(
        "NivelBadge", parent=styles["Normal"], fontSize=15, textColor=colors.white,
        backColor=cor_nivel, alignment=1, spaceBefore=4, spaceAfter=14, borderPadding=8,
        leading=19,
    )

    story = [
        Paragraph("Programa Constelação CallMed", titulo),
        Paragraph(f"Comunicado individual — {mes_ref}", subtitulo),
        HRFlowable(width="100%", thickness=1, color=cor_linha),
        Spacer(1, 14),
        Paragraph(f"<b>Médico(a):</b> {nome_medico}", corpo),
        Spacer(1, 6),
        Paragraph(f"NÍVEL {int(nivel_vestido)} — {pct_aumento_exibido}% de aumento no plantão", badge_style),
    ]

    linhas_tabela = [
        ["Total de plantões no mês", str(int(n_plantoes))],
        ["Plantões em FDS (Sáb/Dom)", str(int(n_fds))],
        ["Plantões noturnos", str(int(n_noturno))],
    ]
    if tempo_no_nivel is not None:
        linhas_tabela.append(["Tempo no nível atual", f"{int(tempo_no_nivel)} mês(es)"])
    tabela = Table(linhas_tabela, colWidths=[10 * cm, 5.4 * cm])
    tabela.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, cor_linha),
        ("TEXTCOLOR", (0, 0), (0, -1), cor_texto_leve),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(tabela)

    story.append(Paragraph(f"Seus benefícios no Nível {int(nivel_vestido)}", h2))
    for b in core.beneficios_acumulados(nivel_vestido):
        # "-" em vez de bullet unicode (•) - fontes base do reportlab (Helvetica) nem sempre tem
        # esse glifo, mesmo problema documentado pra emoji/simbolos fora do Latin-1.
        story.append(Paragraph(f"-  {b}", beneficio_style))

    if proximo_nivel_info:
        story.append(Paragraph("Rumo ao próximo nível", h2))
        partes = []
        if proximo_nivel_info["faltam_plantoes"] > 0:
            partes.append(f"{proximo_nivel_info['faltam_plantoes']} plantão(ões)")
        if proximo_nivel_info["faltam_fds_ou_noturno"] > 0:
            partes.append(f"{proximo_nivel_info['faltam_fds_ou_noturno']} plantão(ões) de FDS/noturno")
        if partes:
            texto = (
                f"Faltam {' e '.join(partes)} no mês para sustentar o "
                f"{proximo_nivel_info['proximo_nivel']}."
            )
        else:
            texto = (
                f"O volume deste mês já sustenta o {proximo_nivel_info['proximo_nivel']} — "
                "o benefício passa a valer após o período de carência, se mantido nos próximos meses."
            )
        story.append(Paragraph(texto, corpo))

    story.append(Spacer(1, 26))
    story.append(HRFlowable(width="100%", thickness=0.5, color=cor_linha))
    rodape = ParagraphStyle(
        "Rodape", parent=styles["Normal"], fontSize=8, textColor=cor_texto_leve, spaceBefore=6,
    )
    story.append(Paragraph(
        f"CallMed Plantões — Grupo CM Callegaro · Emitido em {datetime.now().strftime('%d/%m/%Y')} "
        "· Documento informativo, sujeito às regras vigentes do Programa Constelação.",
        rodape,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
