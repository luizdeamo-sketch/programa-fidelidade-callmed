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


def _fmt_tempo_casa(n_meses):
    """Mesmo formato de app.py:fmt_tempo_casa() - 'X anos e Y meses' em vez de meses crus
    (pedido do usuário 2026-08-22). Duplicado aqui de propósito (mesmo padrão de _fmt_brl acima),
    pra não criar dependência entre os dois módulos só por causa de um helper pequeno."""
    anos, meses = divmod(int(n_meses), 12)
    partes = []
    if anos > 0:
        partes.append(f"{anos} ano" + ("s" if anos != 1 else ""))
    if meses > 0 or anos == 0:
        partes.append(f"{meses} mês" if meses == 1 else f"{meses} meses")
    return " e ".join(partes)


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
    nome_medico, mes_ref, nivel_pagamento, n_plantoes, n_fds, n_noturno, pct_aumento_exibido,
    plantoes_detalhe, valor_total_plantoes, valor_bonificacao,
    nivel_beneficios=None, especialidade=None,
    tempo_no_nivel=None, proximo_nivel_info=None, tempo_de_casa=None, primeiro_mes=None,
    historico_mensal=None,
):
    """Monta o PDF em memória e retorna os bytes prontos pra um st.download_button.

    'nivel_pagamento' (antes chamado 'nivel_vestido') rege o badge/% de aumento no plantão - vale
    na hora, por volume, sem esperar carência (esclarecido pelo usuário 2026-08-20). Se
    'nivel_beneficios' vier diferente (carência do nível de pagamento ainda não cumprida - ver
    core.calcular_niveis), a lista "Seus benefícios" reflete esse nível mais baixo e o PDF avisa
    a diferença; se não vier, usa o mesmo valor de nivel_pagamento (comportamento antigo).

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
    nivel_beneficios = nivel_pagamento if nivel_beneficios is None else nivel_beneficios
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

    cor_nivel = CORES_NIVEL.get(int(nivel_pagamento), colors.grey)
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
        Paragraph(
            f"<b>Médico(a):</b> {nome_medico}"
            + (f" &nbsp;·&nbsp; <b>Especialidade:</b> {especialidade}" if especialidade else ""),
            corpo,
        ),
        Spacer(1, 6),
        Paragraph(f"NÍVEL {int(nivel_pagamento)} — {pct_aumento_exibido}% de aumento no plantão", badge_style),
        # % exibido e arredondado (ex.: Nivel 4 mostra 5%, valor real usa 4,5%) - notinha pra nao
        # parecer que bateu errado se alguem conferir o calculo de cabeca (pedido do usuario,
        # 2026-08-21, pra nao virar risco de confianca agora que o PDF vai pro medico de verdade).
        Paragraph(
            "*% de aumento arredondado para exibição — o valor da bonificação abaixo é calculado "
            "sobre a taxa exata configurada no programa, pode diferir de poucos centavos do "
            "cálculo de cabeça com o % arredondado.",
            ParagraphStyle("CaveatPct", parent=styles["Normal"], fontSize=7.5,
                            textColor=cor_texto_leve, spaceBefore=2, spaceAfter=10),
        ),
    ]

    linhas_tabela = [
        ["Total de plantões no mês", str(int(n_plantoes))],
        ["Plantões em FDS (Sáb/Dom)", str(int(n_fds))],
        ["Plantões noturnos", str(int(n_noturno))],
    ]
    if tempo_no_nivel is not None:
        linhas_tabela.append(["Tempo no nível atual", f"{int(tempo_no_nivel)} mês(es)"])
    if tempo_de_casa is not None:
        texto_tempo_casa = _fmt_tempo_casa(tempo_de_casa)
        if primeiro_mes:
            texto_tempo_casa += f" (desde {primeiro_mes})"
        linhas_tabela.append(["Tempo com a CallMed", texto_tempo_casa])
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
    valor_total_geral = valor_total_plantoes + valor_bonificacao
    linhas_pl.append(["Total de plantões", "", "", _fmt_brl(valor_total_plantoes)])
    linhas_pl.append([
        f"Bonificação Nível {int(nivel_pagamento)} ({pct_aumento_exibido}% sobre o total acima)",
        "", "", _fmt_brl(valor_bonificacao),
    ])
    linhas_pl.append(["Total geral (plantões + bonificação)", "", "", _fmt_brl(valor_total_geral)])

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
        ("SPAN", (0, -3), (2, -3)),
        ("SPAN", (0, -2), (2, -2)),
        ("SPAN", (0, -1), (2, -1)),
        ("ALIGN", (0, -3), (2, -3), "RIGHT"),
        ("ALIGN", (0, -2), (2, -2), "RIGHT"),
        ("ALIGN", (0, -1), (2, -1), "RIGHT"),
        ("FONTNAME", (0, -3), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -3), (-1, -3), 0.75, cor_texto),
        # Total geral (plantões + bonificação) - linha final em destaque, pedido do usuário
        # (2026-08-20) pra deixar claro o quanto o médico recebe no total, não só a bonificação.
        ("LINEABOVE", (0, -1), (-1, -1), 1, cor_texto),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EFF6FF")),
        ("FONTSIZE", (0, -1), (-1, -1), 10.5),
        ("TOPPADDING", (0, -1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
    ]))
    story.append(tabela_pl)
    story.append(Spacer(1, 4))

    story.append(Paragraph(f"Seus benefícios no Nível {int(nivel_beneficios)}", h2))
    for b in core.beneficios_acumulados(nivel_beneficios):
        # "-" em vez de bullet unicode (•) - fontes base do reportlab (Helvetica) nem sempre tem
        # esse glifo, mesmo problema documentado pra emoji/simbolos fora do Latin-1.
        story.append(Paragraph(f"-  {b}", beneficio_style))
    if int(nivel_pagamento) != int(nivel_beneficios):
        # Cobre os dois sentidos - pagamento a frente (caso normal) e beneficios a frente (caso
        # do "colchao" contra queda pontual - um mes fraco isolado nao tira o que ja foi
        # conquistado, ver core.MESES_TOLERANCIA_QUEDA_BENEFICIOS). Achado real 2026-08-21: essa
        # nota so cobria o primeiro sentido, ficava invertida/enganosa no segundo caso.
        if int(nivel_pagamento) > int(nivel_beneficios):
            texto_caveat_beneficios = (
                f"O aumento no valor do plantão já é o do Nível {int(nivel_pagamento)} desde já "
                f"(não espera carência). Os benefícios extras do Nível {int(nivel_pagamento)} "
                "(seguro, cursos, licenças) liberam assim que a carência desse nível for cumprida."
            )
        else:
            texto_caveat_beneficios = (
                f"O volume deste mês sustenta o Nível {int(nivel_pagamento)} no aumento do "
                f"plantão. Os benefícios extras continuam sendo os do Nível {int(nivel_beneficios)} "
                "— um mês mais fraco isolado não tira o que já foi conquistado."
            )
        story.append(Paragraph(
            texto_caveat_beneficios,
            ParagraphStyle("CaveatBeneficios", parent=styles["Normal"], fontSize=8.5,
                            textColor=cor_texto_leve, spaceBefore=4),
        ))

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


def gerar_pdf_analitico(df_mensal, indicadores, mes_ref, custo_por_operacao=None):
    """PDF da página '📈 Analítico' - custo mensal do programa (histórico completo) + os
    indicadores macro do mês selecionado, pra levar pra reunião/diretoria sem print de tela
    (pedido do usuário 2026-08-21). Uso interno.

    'df_mensal' é uma lista de dicts (mesmo formato da tabela da tela: anomes/custo_aumento/
    custo_rampup/custo_total). 'indicadores' é um dict com os 5 indicadores macro já calculados:
    mes_ref, mes_anterior (ou None), custo_total, delta_custo_total_pct (ou None),
    pct_custo_repasse, n_bonificados, n_ativos, pct_bonificados, ticket_medio,
    delta_ticket_medio_pct (ou None), custo_medio_bonificado. 'custo_por_operacao' é opcional -
    lista de dicts com operacao/custo_aumento_alocado/custo_rampup/custo_total/n_medicos (mesmo
    formato de core.custo_por_operacao_mes)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        title=f"Analítico CallMed Premium — {mes_ref}",
    )
    styles = getSampleStyleSheet()
    cor_texto = colors.HexColor("#1F2937")
    cor_texto_leve = colors.HexColor("#6B7280")
    cor_linha = colors.HexColor("#E5E7EB")

    subtitulo = ParagraphStyle(
        "SubtituloAnalitico", parent=styles["Normal"], fontSize=11, textColor=cor_texto_leve,
        spaceAfter=12,
    )
    h2 = ParagraphStyle(
        "H2Analitico", parent=styles["Heading2"], fontSize=13, spaceBefore=16, spaceAfter=8,
        textColor=cor_texto,
    )
    cel_style = ParagraphStyle("CelAnalitico", parent=styles["Normal"], fontSize=8, leading=10)

    story = [
        Image(str(_LOGO_PATH), width=_LOGO_LARGURA, height=_LOGO_ALTURA, hAlign="LEFT"),
        Spacer(1, 6),
        Paragraph(f"Analítico — visão histórica do programa (referência: {mes_ref})", subtitulo),
        HRFlowable(width="100%", thickness=1, color=cor_linha),
    ]

    # ---------------------------------------------------------- CUSTO MENSAL DO PROGRAMA
    story.append(Paragraph("Custo mensal do programa", h2))
    linhas_mensal = [["Mês", "Aumento % (nível)", "Bônus ramp-up", "Custo total"]]
    for m in df_mensal:
        linhas_mensal.append([
            m["anomes"], _fmt_brl(m["custo_aumento"]), _fmt_brl(m["custo_rampup"]),
            _fmt_brl(m["custo_total"]),
        ])
    tabela_mensal = Table(linhas_mensal, colWidths=[3 * cm, 4.7 * cm, 4.7 * cm, 4.7 * cm], repeatRows=1)
    tabela_mensal.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, cor_texto),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, cor_linha),
    ]))
    story.append(tabela_mensal)

    # ---------------------------------------------------------- CUSTO POR OPERAÇÃO
    if custo_por_operacao:
        story.append(Paragraph(f"Custo por operação/hospital — {mes_ref}", h2))
        story.append(Paragraph(
            "Aumento % alocado proporcionalmente ao repasse de cada operação dentro do total do "
            "médico no mês (estimativa de concentração, não contabilização exata) — o bônus de "
            "ramp-up já é exato por operação.",
            ParagraphStyle("CaveatOperacao", parent=styles["Normal"], fontSize=7.5,
                            textColor=cor_texto_leve, spaceAfter=6),
        ))
        linhas_op = [["Operação", "Aumento alocado", "Ramp-up", "Total", "Médicos"]]
        for o in custo_por_operacao:
            linhas_op.append([
                Paragraph(str(o["operacao"]), cel_style), _fmt_brl(o["custo_aumento_alocado"]),
                _fmt_brl(o["custo_rampup"]), _fmt_brl(o["custo_total"]), str(o["n_medicos"]),
            ])
        tabela_op = Table(
            linhas_op, colWidths=[5.2 * cm, 3.5 * cm, 3 * cm, 3 * cm, 2.4 * cm], repeatRows=1,
        )
        tabela_op.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, cor_texto),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, cor_linha),
        ]))
        story.append(tabela_op)

    # ---------------------------------------------------------- INDICADORES MACRO
    story.append(Paragraph(f"Indicadores macro — {indicadores['mes_ref']}", h2))
    linhas_ind = [
        ["Custo total do mês", _fmt_brl(indicadores["custo_total"])
         + (f" ({indicadores['delta_custo_total_pct']:+.1f}% vs {indicadores['mes_anterior']})"
            if indicadores.get("delta_custo_total_pct") is not None else "")],
        ["Custo do programa / repasse total", f"{indicadores['pct_custo_repasse']:.1f}%"],
        ["Médicos bonificados (N2+)",
         f"{indicadores['n_bonificados']} de {indicadores['n_ativos']} "
         f"({indicadores['pct_bonificados']:.0f}%)"],
        ["Ticket médio do plantão", _fmt_brl(indicadores["ticket_medio"])
         + (f" ({indicadores['delta_ticket_medio_pct']:+.1f}% vs {indicadores['mes_anterior']})"
            if indicadores.get("delta_ticket_medio_pct") is not None else "")],
        ["Custo médio / médico bonificado", _fmt_brl(indicadores["custo_medio_bonificado"])],
    ]
    tabela_ind = Table(linhas_ind, colWidths=[8 * cm, 9.4 * cm])
    tabela_ind.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, cor_linha),
        ("TEXTCOLOR", (0, 0), (0, -1), cor_texto_leve),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
    ]))
    story.append(tabela_ind)

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=cor_linha))
    rodape_analitico = ParagraphStyle(
        "RodapeAnalitico", parent=styles["Normal"], fontSize=8, textColor=cor_texto_leve,
        spaceBefore=6,
    )
    story.append(Paragraph(
        f"CallMed Plantões — Grupo CM Callegaro · Emitido em {datetime.now().strftime('%d/%m/%Y')} "
        "· Uso interno do time administrativo. Custo de seguro não entra em nenhum número aqui.",
        rodape_analitico,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def gerar_pdf_abordagem(linhas, mes_ref):
    """PDF da lista '📣 Abordagem (quase lá)' - médicos a poucos plantões de subir de nível,
    pro escalista imprimir/levar consigo pra abordar ativamente antes do fim do mês (pedido do
    usuário 2026-08-21). Uso interno, NÃO é o comunicado individual do médico.

    'linhas' é uma lista de dicts com medico/especialidade/n_plantoes/nivel_atual/proximo_nivel/
    proximo_pct/faltam_plantoes/faltam_fds_ou_noturno/ganho_extra_estimado - mesmo formato que a
    tela '📣 Abordagem (quase lá)' já monta pra exibir, sem duplicar o cálculo aqui."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        title=f"Abordagem — quase no próximo nível ({mes_ref})",
    )
    styles = getSampleStyleSheet()
    cor_texto = colors.HexColor("#1F2937")
    cor_texto_leve = colors.HexColor("#6B7280")
    cor_linha = colors.HexColor("#E5E7EB")

    subtitulo = ParagraphStyle(
        "SubtituloAbordagem", parent=styles["Normal"], fontSize=11, textColor=cor_texto_leve,
        spaceAfter=12,
    )

    story = [
        Image(str(_LOGO_PATH), width=_LOGO_LARGURA, height=_LOGO_ALTURA, hAlign="LEFT"),
        Spacer(1, 6),
        Paragraph(f"Abordagem — médicos quase no próximo nível ({mes_ref})", subtitulo),
        HRFlowable(width="100%", thickness=1, color=cor_linha),
        Spacer(1, 10),
    ]

    cel_style = ParagraphStyle("CelAbordagem", parent=styles["Normal"], fontSize=8, leading=10)
    linhas_tabela = [["Médico", "Especialidade", "Plantões", "Nível → Próx.", "Faltam",
                       "FDS/Not.", "Ganho est."]]
    for l in linhas:
        linhas_tabela.append([
            Paragraph(str(l["medico"]), cel_style),
            Paragraph(str(l["especialidade"]), cel_style),
            str(l["n_plantoes"]),
            f"N{l['nivel_atual']} → N{l['proximo_nivel']} ({l['proximo_pct']}%)",
            str(l["faltam_plantoes"]),
            str(l["faltam_fds_ou_noturno"]),
            _fmt_brl(l["ganho_extra_estimado"]),
        ])

    tabela = Table(
        linhas_tabela, colWidths=[4.3 * cm, 2.8 * cm, 1.6 * cm, 3.2 * cm, 1.5 * cm, 1.7 * cm, 2.4 * cm],
        repeatRows=1,
    )
    tabela.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, cor_texto),
        ("ALIGN", (2, 0), (5, -1), "CENTER"),
        ("ALIGN", (6, 0), (6, -1), "RIGHT"),
    ]))
    story.append(tabela)

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=cor_linha))
    rodape_abordagem = ParagraphStyle(
        "RodapeAbordagem", parent=styles["Normal"], fontSize=8, textColor=cor_texto_leve,
        spaceBefore=6,
    )
    story.append(Paragraph(
        f"CallMed Plantões — Grupo CM Callegaro · Emitido em {datetime.now().strftime('%d/%m/%Y')} "
        "· Uso interno do time administrativo. Ganho estimado com base no ticket médio já "
        "realizado no mês, sujeito a variação.",
        rodape_abordagem,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
