"""Gera o PDF do Comunicado Individual do CallMed Premium — a versão feita pra ser entregue ao
médico (não é a mesma tela do sistema, que mostra dado interno tipo custo de seguro pago pela
empresa). Página única, reportlab puro (Platypus), sem depender de fonte/logo externos.
"""
import io
import pathlib
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # sem display - so gera a imagem em memoria, precisa vir antes do pyplot
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

import core

# Logo colorida no cabeçalho do comunicado (mesma marca usada no sistema - arquivo fornecido pelo
# usuário na sessão 2026-08-20). Proporção original 2875x1688 preservada pra não distorcer.
_LOGO_PATH = pathlib.Path(__file__).parent / "assets" / "logo_horizontal_colorida.png"
_LOGO_LARGURA = 6.5 * cm
_LOGO_ALTURA = _LOGO_LARGURA * (1688 / 2875)

CORES_NIVEL = {
    1: colors.HexColor("#6B7280"),
    2: colors.HexColor("#2563EB"),
    3: colors.HexColor("#7C3AED"),
    4: colors.HexColor("#B45309"),
}


def _fmt_brl(v):
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _gerar_grafico_historico(historico_mensal):
    """Grafico de barras (plantoes) + linha (valor recebido) por mes, em memoria (PNG). Cor
    combinando com o badge de nivel (roxo/laranja) - so pra reforcar engajamento, o usuario
    especificamente pediu algo visual pra motivar o medico a bater mais plantoes."""
    meses = [h["mes"] for h in historico_mensal]
    plantoes = [h["n_plantoes"] for h in historico_mensal]
    valores = [h["valor"] for h in historico_mensal]

    fig, ax1 = plt.subplots(figsize=(6.6, 2.7), dpi=150)
    cor_barra, cor_linha_grafico = "#7C3AED", "#B45309"
    ax1.bar(meses, plantoes, color=cor_barra, alpha=0.85, label="Plantões", zorder=2)
    ax1.set_ylabel("Plantões", color=cor_barra, fontsize=8)
    ax1.tick_params(axis="y", labelcolor=cor_barra, labelsize=7)
    ax1.tick_params(axis="x", labelsize=7, rotation=40)
    for spine in ("top",):
        ax1.spines[spine].set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(meses, valores, color=cor_linha_grafico, marker="o", markersize=3.5, linewidth=1.6,
              label="Valor recebido (R$)", zorder=3)
    ax2.set_ylabel("Valor recebido (R$)", color=cor_linha_grafico, fontsize=8)
    ax2.tick_params(axis="y", labelcolor=cor_linha_grafico, labelsize=7)
    ax2.spines["top"].set_visible(False)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def gerar_pdf_comunicado(
    nome_medico, mes_ref, nivel_vestido, n_plantoes, n_fds, n_noturno, pct_aumento_exibido,
    plantoes_detalhe, valor_total_plantoes, valor_bonificacao,
    tempo_no_nivel=None, proximo_nivel_info=None, tempo_de_casa=None, historico_mensal=None,
):
    """Monta o PDF em memória e retorna os bytes prontos pra um st.download_button.

    'plantoes_detalhe' e uma lista de dicts {"data": "dd/mm/aaaa", "operacao": str, "tipo": str,
    "valor": float} - SO os plantoes que contam pro programa no mes (mesmo escopo que gerou
    n_plantoes/valor_total_plantoes), pra bater com os totais mostrados. Um medico com plantao
    excluido (ex.: tipo nao-clinico, ou operacao fora do escopo) nao aparece aqui - e por isso que
    da pra confiar que "Total de plantoes" bate com a soma das linhas listadas.

    'proximo_nivel_info' pode incluir tambem 'proximo_pct_exibido' e 'ganho_extra_estimado' (R$)
    alem de faltam_plantoes/faltam_fds_ou_noturno/proximo_nivel - se vierem, mostra a projecao
    financeira de bater o proximo nivel ainda este mes (pedido do usuario pra engajar o medico).

    'historico_mensal' e uma lista de dicts {"mes": "aaaa-mm", "n_plantoes": int, "valor": float}
    (tipicamente os ultimos 12 meses) - vira o grafico de historico com a CallMed."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=2.2 * cm, bottomMargin=2 * cm, leftMargin=2.4 * cm, rightMargin=2.4 * cm,
        title=f"Comunicado CallMed Premium — {nome_medico}",
    )
    styles = getSampleStyleSheet()
    cor_texto = colors.HexColor("#1F2937")
    cor_texto_leve = colors.HexColor("#6B7280")
    cor_linha = colors.HexColor("#E5E7EB")

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
        Image(str(_LOGO_PATH), width=_LOGO_LARGURA, height=_LOGO_ALTURA, hAlign="LEFT"),
        Spacer(1, 6),
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
    if tempo_de_casa is not None:
        linhas_tabela.append(["Tempo com a CallMed", f"{int(tempo_de_casa)} mês(es)"])
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

    # ---------------------------------------------------------- PLANTÕES DO MÊS, DETALHADO
    story.append(Paragraph("Plantões realizados no mês", h2))
    cel_style = ParagraphStyle("CelTabela", parent=styles["Normal"], fontSize=8.5, leading=10.5)
    linhas_pl = [["Data", "Operação", "Tipo", "Valor"]]
    for p in plantoes_detalhe:
        linhas_pl.append([
            p["data"], Paragraph(str(p["operacao"]), cel_style), Paragraph(str(p["tipo"]), cel_style),
            _fmt_brl(p["valor"]),
        ])
    linhas_pl.append(["Total de plantões", "", "", _fmt_brl(valor_total_plantoes)])
    linhas_pl.append([
        f"Bonificação Nível {int(nivel_vestido)} ({pct_aumento_exibido}% sobre o total acima)",
        "", "", _fmt_brl(valor_bonificacao),
    ])

    tabela_pl = Table(
        linhas_pl, colWidths=[2.3 * cm, 6.4 * cm, 4.2 * cm, 2.5 * cm], repeatRows=1,
    )
    tabela_pl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, cor_texto),
        ("SPAN", (0, -2), (2, -2)),
        ("SPAN", (0, -1), (2, -1)),
        ("ALIGN", (0, -2), (2, -2), "RIGHT"),
        ("ALIGN", (0, -1), (2, -1), "RIGHT"),
        ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -2), (-1, -2), 0.75, cor_texto),
    ]))
    story.append(tabela_pl)
    story.append(Spacer(1, 4))

    story.append(Paragraph(f"Seus benefícios no Nível {int(nivel_vestido)}", h2))
    for b in core.beneficios_acumulados(nivel_vestido):
        # "-" em vez de bullet unicode (•) - fontes base do reportlab (Helvetica) nem sempre tem
        # esse glifo, mesmo problema documentado pra emoji/simbolos fora do Latin-1.
        story.append(Paragraph(f"-  {b}", beneficio_style))

    if proximo_nivel_info:
        story.append(Paragraph("Alcance o próximo nível ainda este mês", h2))
        partes = []
        if proximo_nivel_info["faltam_plantoes"] > 0:
            partes.append(f"{proximo_nivel_info['faltam_plantoes']} plantão(ões)")
        if proximo_nivel_info["faltam_fds_ou_noturno"] > 0:
            partes.append(f"{proximo_nivel_info['faltam_fds_ou_noturno']} plantão(ões) de FDS/noturno")
        ganho_extra = proximo_nivel_info.get("ganho_extra_estimado")
        pct_prox = proximo_nivel_info.get("proximo_pct_exibido")
        if partes:
            texto = (
                f"Fazendo mais {' e '.join(partes)} este mês, você alcança o "
                f"{proximo_nivel_info['proximo_nivel']}"
                + (f" ({pct_prox}% de aumento no plantão)" if pct_prox is not None else "") + "."
            )
            if ganho_extra:
                texto += (
                    f" Isso representa aproximadamente <b>{_fmt_brl(ganho_extra)} a mais</b> de "
                    "bonificação neste mês (estimativa com base no seu ticket médio por plantão)."
                )
        else:
            texto = (
                f"O volume deste mês já sustenta o {proximo_nivel_info['proximo_nivel']} — "
                "o benefício passa a valer após o período de carência, se mantido nos próximos meses."
            )
        story.append(Paragraph(texto, corpo))
        caveat = ParagraphStyle(
            "Caveat", parent=styles["Normal"], fontSize=8, textColor=cor_texto_leve, spaceBefore=4,
        )
        story.append(Paragraph(
            "Estimativa sujeita ao período de carência do nível e ao mínimo de plantões em FDS/"
            "noturno exigido — consulte o setor administrativo para confirmar.",
            caveat,
        ))

    if historico_mensal:
        story.append(Paragraph("Seu histórico com a CallMed", h2))
        grafico_buf = _gerar_grafico_historico(historico_mensal)
        story.append(Image(grafico_buf, width=16 * cm, height=6.5 * cm))
        story.append(Paragraph(
            f"Plantões e valor recebido nos últimos {len(historico_mensal)} meses.",
            ParagraphStyle("LegendaGrafico", parent=styles["Normal"], fontSize=8,
                            textColor=cor_texto_leve, spaceBefore=2),
        ))

    story.append(Spacer(1, 26))
    story.append(HRFlowable(width="100%", thickness=0.5, color=cor_linha))
    rodape = ParagraphStyle(
        "Rodape", parent=styles["Normal"], fontSize=8, textColor=cor_texto_leve, spaceBefore=6,
    )
    story.append(Paragraph(
        f"CallMed Plantões — Grupo CM Callegaro · Emitido em {datetime.now().strftime('%d/%m/%Y')} "
        "· Documento informativo, sujeito às regras vigentes do CallMed Premium.",
        rodape,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
