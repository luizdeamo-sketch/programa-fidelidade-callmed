"""CallMed Premium - sistema interno, uso exclusivo do time administrativo (médicos não têm
acesso - decisão do usuário, sessão 2026-08-18). Nome oficial do sistema confirmado pelo usuário
em 2026-08-20: "CallMed Premium", só isso - nomes anteriores usados no código/documentos
("Programa Fidelidade CallMed", "Programa Constelação") ficam só como referência histórica interna.

Papéis: master (Luiz - único que pode disparar o bônus de hospital em ramp-up, ação com custo
real), gestor e analista (veem tudo, não disparam ações sensíveis).

Aviso de segurança: login por e-mail + senha em texto puro, sem hash, sem recuperação de senha.
Serve pra identificar quem é quem dentro de um grupo pequeno e confiável (3 pessoas do time adm),
NÃO é proteção contra acesso mal intencionado. Antes de considerar isso "seguro de verdade",
trocar as senhas em usuarios.py e, se for para produção real, migrar para algo como a versão
Lovable já discutida.
"""
import copy
import io
import json
import pathlib

import streamlit as st
import pandas as pd
import core
import usuarios
import comunicado_pdf
import supabase_client

# Marca (logo em variações - fundo claro/escuro, colorida/mono - sessão 2026-08-20, arquivos
# fornecidos pelo usuário). ASSETS_DIR e os caminhos ficam antes do set_page_config porque o
# favicon precisa do caminho do ícone já resolvido.
ASSETS_DIR = pathlib.Path(__file__).parent / "assets"
LOGO_COLORIDA = ASSETS_DIR / "logo_horizontal_colorida.png"
ICONE_CM_AZUL = ASSETS_DIR / "icone_cm_azul.png"

st.set_page_config(page_title="CallMed Premium", page_icon=str(ICONE_CM_AZUL), layout="wide")


@st.cache_data(ttl=3600, show_spinner="Lendo base de plantões (Supabase)...")
def carregar_linhas_brutas(apoio_json):
    """Le a base de plantoes inteira do Supabase - nao depende mais de acesso a maquina/OneDrive
    (migracao 2026-08-20). Cacheada tambem pelo JSON do mapeamento Apoio (tela '🗂️ Apoio'), entao
    so recalcula de fato quando o master edita uma classificacao ou depois de um novo upload (ver
    'Fonte de dados', que limpa esse cache)."""
    if apoio_json and apoio_json != "[]":
        apoio_df = pd.read_json(io.StringIO(apoio_json))
    else:
        apoio_df = pd.DataFrame(columns=["local", "coordenador", "setor_definido", "especialidade_apoio"])
    client = supabase_client.get_client()
    return core.consultar_plantoes_supabase(client, apoio_df=apoio_df)


def apoio_para_json(apoio_df):
    """Serializa o mapeamento Apoio (DataFrame) pra uma chave de cache estavel - ordenado por
    Local pra nao invalidar o cache so por causa de ordem de linha diferente."""
    if apoio_df is None or apoio_df.empty:
        return "[]"
    colunas = ["local", "coordenador", "setor_definido", "especialidade_apoio"]
    return apoio_df[colunas].sort_values("local").to_json(orient="records", force_ascii=False)


@st.cache_data(ttl=3600, show_spinner=False)
def agregar_com_operacoes(df_linhas, operacoes_excluidas_tuple):
    """Aplica a lista de operacoes excluidas (tela Operacoes) e agrega. Cacheado pela tupla de
    operacoes excluidas - so recalcula de fato quando o master muda alguma coisa la."""
    df_ajustado = core.aplicar_operacoes_customizadas(df_linhas, set(operacoes_excluidas_tuple))
    return core.agregar_mensal(df_ajustado)


@st.cache_data(ttl=3600, show_spinner="Recalculando níveis com os parâmetros atuais...")
def calcular_niveis_cached(agg, niveis_json, medicos_gestores_tuple, custo_seguro_total):
    """Cacheado pelo JSON dos parametros + tupla de gestores manuais + custo do seguro - so
    recalcula de fato quando algum dos tres muda."""
    niveis = json.loads(niveis_json)
    return core.calcular_niveis(
        agg, niveis=niveis, medicos_gestores=set(medicos_gestores_tuple),
        custo_seguro_mes=custo_seguro_total,
    )


def niveis_para_json(niveis):
    return json.dumps(niveis, sort_keys=True)


def fmt_brl(v):
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def fmt_brl_md(v):
    """Mesmo formato de fmt_brl, mas com o "$" escapado ("\\$") - streamlit trata "$" como
    delimitador de matemática dentro de st.markdown, e duas ocorrências (ex.: valor final + valor
    do ganho) na MESMA chamada quebram a renderização (vira texto cru em vez de negrito/HTML) -
    bug real encontrado na Calculadora de Plantão, 2026-08-20. Usar sempre que fmt_brl aparecer
    dentro de um st.markdown/unsafe_allow_html junto de outro texto formatado."""
    return fmt_brl(v).replace("$", "\\$")


def badge_nivel(n):
    cores = {1: "#9CA3AF", 2: "#60A5FA", 3: "#A78BFA", 4: "#FBBF24"}
    return f'<span style="background:{cores.get(n,"#999")};color:#111;padding:2px 10px;border-radius:12px;font-weight:600;">Nível {n}</span>'


def renderizar_simulacao_niveis(row):
    """Bloco 'Simulação — quanto falta pra cada nível acima' (pedido do usuário 2026-08-20,
    depois pedido de novo pra aparecer também ao selecionar o médico na Tabela de médicos da
    Visão Geral - mesmo dia). Compartilhado entre renderizar_relatorio_medico (aba Visão Sistema)
    e a Consulta por médico, pra não duplicar a lógica de exibição - mesmo padrão do resto do
    arquivo (função compartilhada em vez de copiar/colar)."""
    sim_niveis = core.simular_todos_niveis(row)
    st.markdown("**Simulação — quanto falta pra cada nível acima**")
    if not sim_niveis:
        st.success("Já está no Nível 4 — nível máximo do programa.")
        return
    for sim in sim_niveis:
        partes_sim = []
        if sim["faltam_plantoes"] > 0:
            partes_sim.append(f"{sim['faltam_plantoes']} plantão(ões)")
        if sim["faltam_fds_ou_noturno"] > 0:
            partes_sim.append(f"{sim['faltam_fds_ou_noturno']} de FDS/noturno")
        texto_falta = (
            f"faltam **{' e '.join(partes_sim)}** este mês" if partes_sim
            else "**já sustentado** pelo volume deste mês (aguardando carência)"
        )
        complemento_valor = (
            f" — cerca de **{fmt_brl_md(sim['ganho_extra_estimado'])} a mais** de bonificação"
            if sim["ganho_extra_estimado"] > 0 else ""
        )
        st.markdown(
            f"{badge_nivel(sim['nivel_idx'])} &nbsp; ({sim['pct_exibido']}% de aumento) — "
            f"{texto_falta}{complemento_valor}.",
            unsafe_allow_html=True,
        )
    st.caption(
        "Estimativa de ganho com base no ticket médio dos plantões já feitos neste mês — pode "
        "variar conforme o valor real dos próximos plantões."
    )


def renderizar_relatorio_medico(nome_medico, mes_referencia):
    """Conteúdo completo do relatório de um médico (abas 🖥️ Visão Sistema + 📋 Comunicado, com
    botão de PDF) - função compartilhada entre a página dedicada '📄 Relatório do Médico' e o
    clique numa linha da tabela de médicos na Visão Geral (pedido do usuário 2026-08-20: mesmo
    conteúdo nos dois lugares, sem duplicar lógica). Usa df_linhas/niveis_df do escopo global -
    já estão montados no momento em que essa função é chamada (depois do login/carregamento)."""
    hist_rel = niveis_df[niveis_df["medico"] == nome_medico].sort_values("anomes")
    if hist_rel.empty:
        st.warning("Sem histórico pra esse médico.")
        return

    if mes_referencia in hist_rel["anomes"].values:
        atual_rel = hist_rel[hist_rel["anomes"] == mes_referencia].iloc[0]
    else:
        atual_rel = hist_rel.iloc[-1]
        st.warning(
            f"Sem dado em {mes_referencia} pra esse médico — mostrando o último mês disponível "
            f"({atual_rel['anomes']})."
        )

    # nivel_pagamento (nivel_bruto) rege o % de aumento no plantao - vale na hora, sem carencia
    # (esclarecido pelo usuario 2026-08-20). nivel_beneficios (nivel_vestido) so rege os
    # BENEFICIOS extras (seguro, curso, licenca), que ainda esperam a carencia - ver docstring de
    # core.calcular_niveis().
    nivel_pagamento_rel = int(atual_rel["nivel_bruto"])
    info_pagamento_rel = core.NIVEL_POR_IDX[nivel_pagamento_rel]
    nivel_beneficios_rel = int(atual_rel["nivel_vestido"])
    info_beneficios_rel = core.NIVEL_POR_IDX[nivel_beneficios_rel]
    tempo_nivel_pagamento_rel = atual_rel["streak_nivel_bruto"]
    tempo_nivel_pagamento_rel = (
        int(tempo_nivel_pagamento_rel) if pd.notna(tempo_nivel_pagamento_rel) else None
    )
    prox_info_rel = core.proximo_nivel_info(atual_rel)
    primeiro_mes_rel = hist_rel["anomes"].min()
    # hist_rel ja tem 1 linha por mes desde o primeiro plantao do medico ate o mes mais recente da
    # base inteira (meses sem plantao viram linha com 0, pra carencia funcionar certo - ver
    # calcular_niveis) - entao len(hist_rel) e literalmente "quantos meses de casa", sem gap.
    tempo_de_casa_rel = len(hist_rel)
    meses_por_nivel_rel = core.meses_por_nivel(hist_rel)

    # Especialidade predominante do medico (pedido do usuario 2026-08-20, mostrar do lado do
    # nome) - moda entre TODOS os plantoes dele na base (nao so o mes de referencia), pra nao
    # oscilar mes a mes por causa de um plantao avulso fora da especialidade principal.
    especialidades_medico_rel = df_linhas.loc[df_linhas["medico"] == nome_medico, "especialidade"]
    especialidades_medico_rel = especialidades_medico_rel[especialidades_medico_rel != ""]
    moda_especialidade_rel = especialidades_medico_rel.mode()
    especialidade_rel = moda_especialidade_rel.iat[0] if not moda_especialidade_rel.empty else "—"

    # Projecao financeira de bater o proximo nivel ainda este mes (pedido do usuario, pra engajar
    # o medico): usa o ticket medio por plantao do proprio mes pra estimar o valor de repasse SE
    # ele completasse os plantoes que faltam, e aplica o % do proximo nivel em cima disso. E uma
    # estimativa (o ticket medio dos proximos plantoes pode ser diferente do que ja fez), por isso
    # o comunicado deixa isso explicito como aproximacao.
    if prox_info_rel:
        n_plantoes_atual = int(atual_rel["n_plantoes"])
        ticket_medio_rel = (
            float(atual_rel["valor_repasse"]) / n_plantoes_atual if n_plantoes_atual > 0 else 0.0
        )
        valor_projetado_rel = (
            float(atual_rel["valor_repasse"]) + prox_info_rel["faltam_plantoes"] * ticket_medio_rel
        )
        prox_nivel_idx_rel = int(atual_rel["nivel_bruto"]) + 1
        info_prox_nivel_rel = core.NIVEL_POR_IDX[prox_nivel_idx_rel]
        ganho_projetado_rel = valor_projetado_rel * info_prox_nivel_rel["pct_aumento"]
        prox_info_rel = {
            **prox_info_rel,
            "proximo_pct_exibido": info_prox_nivel_rel["pct_exibido"],
            "ganho_extra_estimado": max(
                0.0, ganho_projetado_rel - float(atual_rel["custo_aumento_pct_mes"])
            ),
        }

    # Historico recente (ultimos 12 meses TERMINANDO no mes do relatorio, nao no mes mais recente
    # da base inteira - importante pra quando o admin navega pra um mes passado) pro grafico do
    # comunicado - plantoes + valor recebido.
    historico_mensal_rel = [
        {"mes": row["anomes"], "n_plantoes": int(row["n_plantoes"]), "valor": float(row["valor_repasse"])}
        for _, row in hist_rel[hist_rel["anomes"] <= mes_referencia].tail(12).iterrows()
    ]

    aba_sistema, aba_medico = st.tabs(["🖥️ Visão Sistema", "📋 Comunicado ao Médico"])

    # ---------------------------------------------------------- ABA SISTEMA (interna)
    with aba_sistema:
        st.markdown(
            f"### {nome_medico} &nbsp; "
            f"<span style='color:#6B7280;font-weight:400;font-size:0.7em'>{especialidade_rel}</span>",
            unsafe_allow_html=True,
        )
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(
            f"**Nível vigente (pagamento)**<br>{badge_nivel(nivel_pagamento_rel)}",
            unsafe_allow_html=True,
        )
        m2.metric("Tempo de casa", f"{tempo_de_casa_rel} mês(es)", help=f"Desde {primeiro_mes_rel}")
        m3.metric(
            "Tempo no nível atual",
            f"{tempo_nivel_pagamento_rel} mês(es)" if tempo_nivel_pagamento_rel is not None else "—",
            help="Meses consecutivos que o volume sustenta esse nível - vale pro pagamento na hora, "
                 "sem esperar carência.",
        )
        m4.metric("Aumento no plantão", f"{info_pagamento_rel['pct_exibido']}%")

        st.caption(
            "Meses em cada nível (histórico completo, desde "
            f"{primeiro_mes_rel}): Nível 1: {meses_por_nivel_rel[1]} · Nível 2: "
            f"{meses_por_nivel_rel[2]} · Nível 3: {meses_por_nivel_rel[3]} · "
            f"Nível 4: {meses_por_nivel_rel[4]}."
        )

        # Carencia (2/4/6 meses pra N2/N3/N4) so segura os BENEFICIOS extras (seguro, curso,
        # licenca), nao o pagamento - esclarecido pelo usuario 2026-08-20. Se o nivel de
        # pagamento (volume) ja passou do nivel de beneficios (carencia ainda não cumprida),
        # avisa aqui pra não confundir o escalista/médico.
        if nivel_pagamento_rel != nivel_beneficios_rel:
            carencia_necessaria_rel = core.NIVEL_POR_IDX[nivel_pagamento_rel]["carencia_meses"]
            st.info(
                f"O pagamento já está no **Nível {nivel_pagamento_rel}** "
                f"({info_pagamento_rel['pct_exibido']}% de aumento) — não espera carência. Mas os "
                f"**benefícios extras** desse nível (seguro, cursos, licenças) só liberam depois de "
                f"**{carencia_necessaria_rel} mês(es) consecutivos** nesse volume; hoje os benefícios "
                f"ativos ainda são os do **Nível {nivel_beneficios_rel}**."
            )

        st.markdown("---")
        renderizar_simulacao_niveis(atual_rel)

        st.markdown(f"#### Plantões em {mes_referencia}")
        plantoes_mes_rel = df_linhas[
            (df_linhas["medico"] == nome_medico) & (df_linhas["anomes"] == mes_referencia)
        ].sort_values("data_dt")
        if plantoes_mes_rel.empty:
            st.caption("Nenhum plantão lançado nesse mês.")
        else:
            st.dataframe(
                plantoes_mes_rel[["data_dt", "operacao", "tipo", "valor", "eh_fds", "eh_noturno",
                                   "conta_pro_nivel"]]
                .rename(columns={
                    "data_dt": "Data", "operacao": "Operação", "tipo": "Tipo", "valor": "Valor",
                    "eh_fds": "FDS", "eh_noturno": "Noturno", "conta_pro_nivel": "Contou pro nível",
                })
                .style.format({
                    "Valor": fmt_brl,
                    "Data": lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "—",
                }),
                use_container_width=True, hide_index=True,
            )

            # Transparencia sobre POR QUE cada linha conta (ou nao) - pedido do usuario apos notar
            # um medico (Sergio Gratão) com plantao contando pro programa sem ser anestesista de
            # verdade. Desde 2026-08-20 o sistema cruza contra a aba "Apoio" do proprio arquivo de
            # plantoes (fonte de verdade oficial pro Setor Definido/Especialidade, mantida pela
            # area - ver core.carregar_apoio()) em vez de confiar na coluna Especialidade da BD,
            # que tem erro de classificacao linha a linha. Essa tabela mostra a comparacao.
            with st.expander("🔍 Por que esses plantões contam (ou não) pro programa?"):
                resumo_combos = (
                    plantoes_mes_rel.groupby(["operacao_bd", "especialidade_bd", "operacao",
                                               "especialidade", "chave_operacao", "sem_match_apoio"])
                    .agg(linhas=("valor", "count"), conta=("conta_pro_nivel", "sum"))
                    .reset_index()
                )
                resumo_combos["Habilitada em Operações"] = ~resumo_combos["chave_operacao"].isin(
                    st.session_state["operacoes_excluidas"]
                )
                resumo_combos["Divergia do relatório original?"] = (
                    resumo_combos["especialidade_bd"] != resumo_combos["especialidade"]
                )
                st.dataframe(
                    resumo_combos[["operacao", "especialidade", "especialidade_bd", "linhas",
                                    "conta", "Habilitada em Operações", "Divergia do relatório original?",
                                    "sem_match_apoio"]]
                    .rename(columns={
                        "operacao": "Operação (Apoio)", "especialidade": "Especialidade (Apoio)",
                        "especialidade_bd": "Especialidade (relatório original)",
                        "linhas": "Linhas no mês", "conta": "Contaram",
                        "sem_match_apoio": "Sem correspondência na aba Apoio",
                    }),
                    use_container_width=True, hide_index=True,
                )
                st.caption(
                    "Operação/Especialidade vêm da aba 'Apoio' do arquivo de plantões (fonte de "
                    "verdade oficial mantida pela área), não da coluna Especialidade lançada na "
                    "aba BD — essa diverge da Apoio em ~2,3% das linhas da base inteira. Se uma "
                    "combinação está com 'Habilitada em Operações' desmarcada, é possível excluir "
                    "esse médico do programa desmarcando ela na tela 🏥 Operações. 'Sem "
                    "correspondência na aba Apoio' marcado é alerta de dado novo — o Local não "
                    "está cadastrado lá ainda, o sistema caiu num critério de reserva menos confiável."
                )

        st.markdown("#### Bônus e custos do mês")
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Valor dos plantões", fmt_brl(atual_rel["valor_repasse"]))
        b2.metric("Valor do aumento", fmt_brl(atual_rel["custo_aumento_pct_mes"]))
        b3.metric("Custo do seguro (empresa)", fmt_brl(atual_rel["custo_seguro_mes"]))
        b4.metric("Total geral", fmt_brl(atual_rel["valor_total_geral"]))

        with st.expander("Ver histórico completo (todos os meses)"):
            st.dataframe(
                hist_rel[["anomes", "n_plantoes", "n_fds", "n_noturno", "nivel_bruto",
                          "nivel_vestido", "valor_repasse", "valor_total_geral"]]
                .rename(columns={
                    "anomes": "Mês", "n_plantoes": "Plantões", "n_fds": "FDS (Sáb/Dom)",
                    "n_noturno": "Noturno", "nivel_bruto": "Nível (pagamento)",
                    "nivel_vestido": "Nível (benefícios)", "valor_repasse": "Valor Plantões",
                    "valor_total_geral": "Total Geral",
                })
                .style.format({"Valor Plantões": fmt_brl, "Total Geral": fmt_brl}),
                use_container_width=True, hide_index=True,
            )

    # ---------------------------------------------------------- ABA MÉDICO (comunicado + PDF)
    with aba_medico:
        st.caption(
            "Versão pronta pra compartilhar com o médico — sem os custos internos pagos pela empresa."
        )
        st.markdown(
            f"### Nível {nivel_pagamento_rel} — {info_pagamento_rel['pct_exibido']}% de aumento no plantão"
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Plantões no mês", int(atual_rel["n_plantoes"]))
        c2.metric("FDS/Noturno", int(atual_rel["n_fds_ou_noturno"]))
        c3.metric(
            "Tempo no nível",
            f"{tempo_nivel_pagamento_rel} mês(es)" if tempo_nivel_pagamento_rel is not None else "—",
        )
        c4.metric("Tempo com a CallMed", f"{tempo_de_casa_rel} mês(es)")

        st.markdown("##### Benefícios inclusos")
        for beneficio in core.beneficios_acumulados(nivel_beneficios_rel):
            st.markdown(f"- {beneficio}")
        if nivel_pagamento_rel != nivel_beneficios_rel:
            st.caption(
                f"Os benefícios acima são os do Nível {nivel_beneficios_rel} (tempo de carência já "
                f"cumprido). O aumento no valor do plantão já é o do Nível {nivel_pagamento_rel} "
                "desde já — os benefícios extras desse nível liberam em breve, sem precisar de "
                "nenhum plantão a mais."
            )

        if prox_info_rel:
            partes_rel = []
            if prox_info_rel["faltam_plantoes"] > 0:
                partes_rel.append(f"{prox_info_rel['faltam_plantoes']} plantão(ões)")
            if prox_info_rel["faltam_fds_ou_noturno"] > 0:
                partes_rel.append(f"{prox_info_rel['faltam_fds_ou_noturno']} plantão(ões) de FDS/noturno")
            if partes_rel:
                msg = f"Faltam {' e '.join(partes_rel)} no mês pro {prox_info_rel['proximo_nivel']}"
                msg += f" ({prox_info_rel['proximo_pct_exibido']}% de aumento)"
                if prox_info_rel["ganho_extra_estimado"] > 0:
                    msg += f" — cerca de **{fmt_brl(prox_info_rel['ganho_extra_estimado'])} a mais** de bonificação neste mês."
                else:
                    msg += "."
                st.info(msg)
            else:
                st.info(
                    f"O volume deste mês já sustenta o {prox_info_rel['proximo_nivel']} — o "
                    "benefício passa a valer após a carência, se mantido nos próximos meses."
                )

        if len(historico_mensal_rel) >= 2:
            st.markdown("##### Histórico com a CallMed")
            hist_chart_df = pd.DataFrame(historico_mensal_rel).set_index("mes")
            cc1, cc2 = st.columns(2)
            cc1.bar_chart(hist_chart_df[["n_plantoes"]].rename(columns={"n_plantoes": "Plantões"}))
            cc2.line_chart(hist_chart_df[["valor"]].rename(columns={"valor": "Valor recebido (R$)"}))
            st.caption(f"Últimos {len(historico_mensal_rel)} meses — prévia; o PDF traz o gráfico completo.")

        # So os plantoes que CONTARAM pro programa (mesmo escopo que gerou n_plantoes/valor_repasse)
        # - um plantao excluido (tipo nao-clinico, operacao fora do escopo etc.) nao aparece no PDF
        # do medico, pra "Total de plantoes" bater exatamente com a soma das linhas listadas.
        plantoes_contados_rel = plantoes_mes_rel[plantoes_mes_rel["conta_pro_nivel"]].sort_values("data_dt")
        plantoes_detalhe_rel = [
            {
                "data": row["data_dt"].strftime("%d/%m/%Y") if pd.notna(row["data_dt"]) else "—",
                "operacao": row["operacao"], "tipo": row["tipo"], "valor": row["valor"],
            }
            for _, row in plantoes_contados_rel.iterrows()
        ]
        pdf_bytes_rel = comunicado_pdf.gerar_pdf_comunicado(
            nome_medico=nome_medico, mes_ref=mes_referencia, nivel_pagamento=nivel_pagamento_rel,
            nivel_beneficios=nivel_beneficios_rel, especialidade=especialidade_rel,
            n_plantoes=int(atual_rel["n_plantoes"]), n_fds=int(atual_rel["n_fds"]),
            n_noturno=int(atual_rel["n_noturno"]), pct_aumento_exibido=info_pagamento_rel["pct_exibido"],
            plantoes_detalhe=plantoes_detalhe_rel, valor_total_plantoes=atual_rel["valor_repasse"],
            valor_bonificacao=atual_rel["custo_aumento_pct_mes"],
            tempo_no_nivel=tempo_nivel_pagamento_rel, proximo_nivel_info=prox_info_rel,
            tempo_de_casa=tempo_de_casa_rel, historico_mensal=historico_mensal_rel,
        )
        st.download_button(
            "📄 Baixar PDF para o médico", data=pdf_bytes_rel,
            file_name=f"comunicado_{nome_medico.replace(' ', '_')}_{mes_referencia}.pdf",
            mime="application/pdf", type="primary", key=f"pdf_{nome_medico}_{mes_referencia}",
        )


# ---------------------------------------------------------------- LOGIN
if "usuario" not in st.session_state:
    col_logo_a, col_logo_b, col_logo_c = st.columns([1, 1, 1])
    with col_logo_b:
        st.image(str(LOGO_COLORIDA), use_container_width=True)
    st.caption("Acesso restrito ao time administrativo")
    with st.form("login"):
        email = st.text_input("E-mail")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar")
    if entrar:
        user = usuarios.autenticar(email, senha)
        if user:
            st.session_state["usuario"] = user
            st.rerun()
        else:
            st.error("E-mail ou senha incorretos.")
    st.stop()

usuario = st.session_state["usuario"]
eh_master = usuario["papel"] in usuarios.PAPEIS_COM_ACAO_SENSIVEL

# Configurações editáveis (níveis/carência, operações excluídas, gestores manuais, custo do
# seguro, parâmetros de ramp-up) agora vêm do Supabase (tabela public.config) na primeira vez que
# a sessão abre - antes viviam só em st.session_state e SE PERDIAM a cada sessão nova/redeploy,
# sem aviso nenhum (achado real na auditoria de 2026-08-20: a tela dizia "aplicado" mas nada
# gravava em lugar permanente). Uma vez carregado pra session_state, o resto do app usa
# normalmente; cada botão "Aplicar"/"Restaurar" agora também grava de volta no Supabase.
_sb = supabase_client.get_client()

if "niveis_custom" not in st.session_state:
    st.session_state["niveis_custom"] = core.consultar_config_supabase(
        _sb, "niveis_custom", copy.deepcopy(core.NIVEIS)
    )
if "apoio_custom" not in st.session_state:
    # Le do Supabase (tabela public.apoio) - fonte de verdade desde a migracao 2026-08-20.
    st.session_state["apoio_custom"] = core.consultar_apoio_supabase(_sb)

df_linhas = carregar_linhas_brutas(apoio_para_json(st.session_state["apoio_custom"]))
if "operacoes_excluidas" not in st.session_state:
    padrao_operacoes = list(core.operacoes_excluidas_por_padrao(df_linhas))
    st.session_state["operacoes_excluidas"] = set(
        core.consultar_config_supabase(_sb, "operacoes_excluidas", padrao_operacoes)
    )
if "medicos_gestores" not in st.session_state:
    st.session_state["medicos_gestores"] = set(
        core.consultar_config_supabase(_sb, "medicos_gestores", [])
    )
if "custo_seguro_vida_dit_funeral" not in st.session_state:
    _seguro_cfg = core.consultar_config_supabase(
        _sb, "custo_seguro",
        {"vida_dit_funeral": core.CUSTO_SEGURO_VIDA_DIT_FUNERAL, "rcp": core.CUSTO_RCP},
    )
    st.session_state["custo_seguro_vida_dit_funeral"] = _seguro_cfg["vida_dit_funeral"]
    st.session_state["custo_seguro_rcp"] = _seguro_cfg["rcp"]
if "rampup_pct" not in st.session_state:
    _rampup_cfg = core.consultar_config_supabase(_sb, "rampup_params", {"pct": 0.05, "duracao_meses": 3})
    st.session_state["rampup_pct"] = _rampup_cfg["pct"]
    st.session_state["rampup_duracao_meses"] = _rampup_cfg["duracao_meses"]
if "rampup_disparos" not in st.session_state:
    st.session_state["rampup_disparos"] = core.consultar_rampup_supabase(_sb)

agg = agregar_com_operacoes(df_linhas, tuple(sorted(st.session_state["operacoes_excluidas"])))
niveis_df = calcular_niveis_cached(
    agg, niveis_para_json(st.session_state["niveis_custom"]),
    tuple(sorted(st.session_state["medicos_gestores"])),
    st.session_state["custo_seguro_vida_dit_funeral"] + st.session_state["custo_seguro_rcp"],
)
if niveis_df.empty:
    st.error("Base de plantões não encontrada ou vazia. Verifique o caminho em config_caminhos.py.")
    st.stop()

# Aplica os bônus de ramp-up já disparados de verdade (tabela public.rampup_disparos) em cima do
# valor_total_geral - antes "Confirmar disparo" só mostrava uma mensagem de sucesso, sem gravar
# nem afetar nenhum cálculo em lugar nenhum (achado real na auditoria de 2026-08-20).
rampup_por_medico_mes = core.calcular_rampup_por_medico_mes(df_linhas, st.session_state["rampup_disparos"])
niveis_df = niveis_df.merge(rampup_por_medico_mes, on=["medico", "anomes"], how="left")
niveis_df["custo_rampup_mes"] = niveis_df["custo_rampup_mes"].fillna(0.0)
niveis_df["valor_total_geral"] = niveis_df["valor_total_geral"] + niveis_df["custo_rampup_mes"]

meses_disponiveis = sorted(niveis_df["anomes"].unique())
# "mes_atual" e a UNICA fonte de verdade do mes selecionado (mesmo key do widget). Os botoes
# Anterior/Seguinte SO PODEM mudar esse session_state via on_click (callback roda ANTES do
# widget ser reinstanciado no proximo run) - setar direto dentro do "if st.button(...):" quebra
# com StreamlitAPIException ("cannot be modified after the widget... is instantiated"), porque
# nesse ponto o widget de mes da MESMA execucao ja rodou antes. Bug real encontrado e corrigido
# em 2026-08-20 (tentativas anteriores com value= e com set direto no if-button falharam). O
# select_slider original virou selectbox no mesmo dia (usuario achou a barra ruim visualmente) -
# a logica de session_state/callback continua igual, so o widget mudou.
if (
    "mes_atual" not in st.session_state
    or st.session_state["mes_atual"] not in meses_disponiveis
):
    st.session_state["mes_atual"] = meses_disponiveis[-1]


def _ir_mes(delta):
    idx = meses_disponiveis.index(st.session_state["mes_atual"])
    novo_idx = idx + delta
    if 0 <= novo_idx < len(meses_disponiveis):
        st.session_state["mes_atual"] = meses_disponiveis[novo_idx]


# Callbacks dos botoes "Restaurar padrao" da tela Regras do Programa (seguro e ramp-up) - tem que
# rodar via on_click, nao dentro de "if st.button():", pelo mesmo motivo do _ir_mes acima: os
# widgets desses campos usam a MESMA key da variavel de session_state (pra "Restaurar padrao"
# tambem resetar o valor exibido, nao so o numero usado no calculo), entao ja estao instanciados
# quando o "if button" seria avaliado nesse mesmo run.
def _restaurar_seguro():
    st.session_state["custo_seguro_vida_dit_funeral"] = core.CUSTO_SEGURO_VIDA_DIT_FUNERAL
    st.session_state["custo_seguro_rcp"] = core.CUSTO_RCP
    core.salvar_config_supabase(
        supabase_client.get_client(), "custo_seguro",
        {"vida_dit_funeral": core.CUSTO_SEGURO_VIDA_DIT_FUNERAL, "rcp": core.CUSTO_RCP},
    )


def _restaurar_rampup():
    st.session_state["input_rampup_pct"] = 5.0
    st.session_state["input_rampup_duracao"] = 3
    st.session_state["rampup_pct"] = 0.05
    st.session_state["rampup_duracao_meses"] = 3
    core.salvar_config_supabase(
        supabase_client.get_client(), "rampup_params", {"pct": 0.05, "duracao_meses": 3}
    )


with st.sidebar:
    st.image(str(ICONE_CM_AZUL), width=56)
    st.markdown(f"**{usuario['nome']}**")
    st.caption(f"Papel: {usuario['papel']}")
    if st.button("Sair"):
        del st.session_state["usuario"]
        st.rerun()
    st.markdown("---")
    pagina = st.radio(
        "Navegação",
        ["📊 Visão Geral", "🏥 Operações", "👔 Gestores", "⚙️ Regras do Programa",
         "📄 Relatório do Médico", "🗂️ Apoio (Local → Especialidade)", "🗄️ Base de Plantões"],
        label_visibility="collapsed",
    )
    st.markdown("---")

    st.selectbox("📅 Mês de referência", options=meses_disponiveis, key="mes_atual")
    idx_atual = meses_disponiveis.index(st.session_state["mes_atual"])
    mcol1, mcol2 = st.columns(2)
    with mcol1:
        st.button("← Anterior", disabled=(idx_atual == 0), use_container_width=True,
                   on_click=_ir_mes, args=(-1,))
    with mcol2:
        st.button("Seguinte →", disabled=(idx_atual == len(meses_disponiveis) - 1), use_container_width=True,
                   on_click=_ir_mes, args=(1,))

    st.markdown("---")

    # ---------------------------------------------------------- CALCULADORA DE PLANTÃO
    # Simulação simples (pedido do usuário, 2026-08-20): quanto um plantão de valor X pagaria em
    # cada nível do programa. Usa niveis_custom (respeita edição feita em "Regras do Programa"),
    # não os percentuais fixos de core.NIVEIS.
    with st.expander("🧮 Calculadora de plantão", expanded=False):
        st.caption(
            "Informe o valor basal de um plantão e veja quanto ele pagaria em cada nível do "
            "programa (mesmos percentuais configurados em 'Regras do Programa')."
        )
        valor_basal_calc = st.number_input(
            "Valor basal do plantão (R$)", min_value=0.0, value=1000.0, step=50.0,
            format="%.2f", key="calc_valor_basal",
        )
        for nivel_calc in sorted(st.session_state["niveis_custom"], key=lambda n: n["idx"]):
            ganho_calc = valor_basal_calc * nivel_calc["pct_aumento"]
            valor_final_calc = valor_basal_calc + ganho_calc
            complemento = (
                f" &nbsp; <span style='color:#6B7280;font-size:0.85em'>(+{fmt_brl_md(ganho_calc)}, "
                f"{nivel_calc['pct_exibido']}%)</span>"
                if nivel_calc["pct_aumento"] else
                " &nbsp; <span style='color:#6B7280;font-size:0.85em'>(valor cheio, sem aumento)</span>"
            )
            st.markdown(
                f"{badge_nivel(nivel_calc['idx'])} &nbsp; **{fmt_brl_md(valor_final_calc)}**{complemento}",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ---------------------------------------------------------- FONTE DE DADOS (upload + mesclagem)
    with st.expander("📁 Fonte de dados (base de plantões)", expanded=False):
        st.caption(
            f"Base no Supabase — {len(df_linhas):,} plantões, {meses_disponiveis[0]} a "
            f"{meses_disponiveis[-1]}. Não depende mais de acesso à máquina/OneDrive; pra "
            "atualizar, envie uma planilha de qualquer período — o sistema identifica sozinho o "
            "que já existe (sobreposição, mantido) e o que é novo (incluído)."
        )
        resumo_envio = st.session_state.pop("resumo_envio_planilha", None)
        if resumo_envio:
            st.success(
                f"Planilha processada: {resumo_envio['linhas_enviadas']:,} linha(s) enviada(s), "
                f"cobrindo {', '.join(resumo_envio['meses'])}. "
                f"**{resumo_envio['novas']:,} nova(s)** incluída(s) — "
                f"{resumo_envio['existentes_antes']:,} já existiam nesses meses antes do envio "
                "(sobreposição, mantidas sem duplicar)."
            )
            if resumo_envio.get("descartadas_valor_invalido"):
                st.warning(
                    f"⚠️ {resumo_envio['descartadas_valor_invalido']:,} linha(s) da planilha "
                    "foram ignoradas por ter valor zero, negativo ou não numérico (não entraram "
                    "no envio acima) — confira se não é uma correção legítima antes de descartar."
                )

        if eh_master:
            novo_arquivo = st.file_uploader(
                "Enviar planilha de plantões (export do pegaplantao.com.br, aba 'BD' antiga "
                "também aceita, qualquer período)",
                type=["xlsx"],
            )
            if novo_arquivo is not None:
                if st.button("📤 Enviar e mesclar"):
                    # Achado real 2026-08-20: planilha com formato errado (sem a aba 'BD') fazia o
                    # app inteiro quebrar com um traceback cru, em vez de um aviso entendível.
                    try:
                        with st.spinner("Lendo a planilha e comparando com o que já está no banco..."):
                            resumo = core.enviar_planilha_supabase(supabase_client.get_client(), novo_arquivo)
                    except core.ArquivoInvalidoError as e:
                        st.error(f"⚠️ Não consegui processar essa planilha: {e}")
                    else:
                        st.session_state["resumo_envio_planilha"] = resumo
                        carregar_linhas_brutas.clear()
                        agregar_com_operacoes.clear()
                        calcular_niveis_cached.clear()
                        st.rerun()
        else:
            st.caption("Envio de novo arquivo é exclusivo do papel master.")

st.image(str(LOGO_COLORIDA), width=260)
st.caption(f"Regras vigentes a partir de {core.GO_LIVE} · dados até {niveis_df['anomes'].max()}")

# ============================================================= PÁGINA: BASE DE PLANTÕES
if pagina == "🗄️ Base de Plantões":
    st.subheader("🗄️ Base de Plantões")
    st.caption(
        f"Visibilidade direta da base bruta (Supabase, tabela 'plantoes') — "
        f"{len(df_linhas):,} linhas, de {meses_disponiveis[0]} a {meses_disponiveis[-1]}, "
        f"{df_linhas['medico'].nunique():,} médicos distintos."
    )

    fc1, fc2, fc3 = st.columns(3)
    opcoes_mes_bd = ["Todos os meses"] + meses_disponiveis
    filtro_mes_bd = fc1.selectbox("Mês", opcoes_mes_bd, index=len(opcoes_mes_bd) - 1)
    filtro_medico_bd = fc2.text_input("Médico contém")
    filtro_local_bd = fc3.text_input("Operação/Local contém")

    tabela_bd = df_linhas
    if filtro_mes_bd != "Todos os meses":
        tabela_bd = tabela_bd[tabela_bd["anomes"] == filtro_mes_bd]
    if filtro_medico_bd:
        tabela_bd = tabela_bd[tabela_bd["medico"].str.contains(filtro_medico_bd, case=False, na=False)]
    if filtro_local_bd:
        tabela_bd = tabela_bd[
            tabela_bd["operacao"].str.contains(filtro_local_bd, case=False, na=False)
            | tabela_bd["local"].str.contains(filtro_local_bd, case=False, na=False)
        ]

    st.caption(f"{len(tabela_bd):,} linha(s) encontrada(s).")
    if len(tabela_bd) > 5000:
        st.warning(
            "Mais de 5.000 linhas — refine os filtros pra uma visualização mais rápida (o "
            "download em CSV, no canto da tabela, traz tudo mesmo assim)."
        )

    st.dataframe(
        tabela_bd[["data_dt", "medico", "operacao", "especialidade", "tipo", "valor",
                   "especialidade_bd", "conta_pro_nivel"]]
        .sort_values("data_dt", ascending=False)
        .rename(columns={
            "data_dt": "Data", "medico": "Médico", "operacao": "Operação",
            "especialidade": "Especialidade", "tipo": "Tipo", "valor": "Valor",
            "especialidade_bd": "Especialidade (original)", "conta_pro_nivel": "Conta pro nível",
        })
        .style.format({
            "Valor": fmt_brl,
            "Data": lambda d: d.strftime("%d/%m/%Y %H:%M") if pd.notna(d) else "—",
        }),
        use_container_width=True, hide_index=True, height=600,
    )
    st.stop()

# ============================================================= PÁGINA: APOIO
if pagina == "🗂️ Apoio (Local → Especialidade)":
    st.subheader("🗂️ Apoio — mapeamento Local → Especialidade")
    st.caption(
        "Fonte de verdade de qual operação/especialidade cada plantão pertence — o sistema não "
        "depende mais de consultar a aba 'Apoio' do Excel a cada carregamento, esse mapeamento "
        "vive aqui e o master edita direto. Local sem classificação aparece no topo da tabela "
        "(volume maior primeiro), pra priorizar o que falta revisar."
    )
    if st.session_state.pop("sucesso_apoio", False):
        st.success("Mapeamento aplicado e salvo — histórico recalculado.")

    resumo_apoio = core.resumo_locais_para_apoio(df_linhas, st.session_state["apoio_custom"])
    n_nao_classificados = int((~resumo_apoio["classificado"]).sum())
    if n_nao_classificados:
        st.warning(
            f"⚠️ {n_nao_classificados} Local(is) sem classificação ainda — aparecem no topo da "
            "tabela abaixo. Enquanto não forem preenchidos, entram no cálculo de nível como se "
            "não fossem Anestesia (ficam de fora por padrão, comportamento conservador)."
        )

    tabela_apoio = resumo_apoio[["local", "total_linhas", "medicos", "coordenador",
                                  "setor_definido", "especialidade_apoio"]].rename(columns={
        "local": "Local (original)", "total_linhas": "Linhas na base", "medicos": "Médicos",
        "coordenador": "Coordenador", "setor_definido": "Setor Definido (operação)",
        "especialidade_apoio": "Especialidade",
    })

    if eh_master:
        tabela_editada = st.data_editor(
            tabela_apoio, use_container_width=True, hide_index=True, key="editor_apoio",
            disabled=["Local (original)", "Linhas na base", "Médicos"], height=500,
        )
        cbtn1, cbtn2 = st.columns(2)
        if cbtn1.button("✅ Aplicar mudanças e recalcular", type="primary"):
            novo_apoio = tabela_editada.rename(columns={
                "Local (original)": "local", "Coordenador": "coordenador",
                "Setor Definido (operação)": "setor_definido", "Especialidade": "especialidade_apoio",
            })[["local", "coordenador", "setor_definido", "especialidade_apoio"]]
            core.salvar_apoio_supabase(supabase_client.get_client(), novo_apoio)
            st.session_state["apoio_custom"] = novo_apoio
            st.session_state["sucesso_apoio"] = True
            st.rerun()
        if cbtn2.button(
            "↩️ Reimportar da planilha local (só funciona rodando na máquina com OneDrive)"
        ):
            apoio_planilha = core.carregar_apoio()
            core.salvar_apoio_supabase(supabase_client.get_client(), apoio_planilha)
            st.session_state["apoio_custom"] = apoio_planilha
            st.session_state["sucesso_apoio"] = True
            st.rerun()
        st.caption(
            "O recálculo roda o histórico inteiro de novo — afeta nível, carência e o valor de "
            "aumento pago a todos os médicos que passam por esses Locais. Mudanças aqui gravam "
            "direto no Supabase (tabela 'apoio'), visível pra qualquer um que acessar o sistema."
        )
    else:
        st.caption("Somente leitura — edição é exclusiva do papel master.")
        st.dataframe(tabela_apoio, use_container_width=True, hide_index=True, height=500)

    st.stop()

# ============================================================= PÁGINA: OPERAÇÕES
if pagina == "🏥 Operações":
    st.subheader("🏥 Operações que contam pro CallMed Premium")
    st.caption(
        "Cada linha é uma combinação **hospital + especialidade** — ex.: 'Hospital São Bernardo' "
        "vira 3 linhas (Anestesia, Enfermaria, UTI), cada uma flegável separadamente. Desmarcar "
        "uma linha tira só aqueles plantões da contagem de nível dos médicos — afeta o histórico "
        "inteiro, não só o mês atual."
    )
    if st.session_state.pop("sucesso_operacoes", False):
        st.success("Lista de operações salva no Supabase e aplicada — histórico recalculado.")

    resumo_op = core.listar_operacoes(df_linhas)
    tabela_op = resumo_op[["chave_operacao", "operacao", "especialidade", "total_linhas", "conta_hoje"]].copy()
    tabela_op["Incluída"] = ~resumo_op["chave_operacao"].isin(st.session_state["operacoes_excluidas"]).values
    tabela_op = tabela_op.rename(columns={
        "operacao": "Operação", "especialidade": "Especialidade",
        "total_linhas": "Total de linhas", "conta_hoje": "Contam hoje",
    })

    if eh_master:
        tabela_editada = st.data_editor(
            tabela_op, use_container_width=True, hide_index=True, key="editor_operacoes",
            column_order=["Operação", "Especialidade", "Total de linhas", "Contam hoje", "Incluída"],
            disabled=["chave_operacao", "Operação", "Especialidade", "Total de linhas", "Contam hoje"],
            column_config={"Incluída": st.column_config.CheckboxColumn(
                help="Desmarque para excluir essa combinação hospital+especialidade do CallMed Premium."
            )},
        )
        if st.button("✅ Aplicar mudanças e recalcular", type="primary"):
            # "chave_operacao" fica no dataframe (so nao aparece na tela, via column_order) pra
            # ler de volta aqui de forma robusta, sem depender da ordem das linhas.
            novas_excluidas = set(
                tabela_editada.loc[~tabela_editada["Incluída"], "chave_operacao"]
            )
            st.session_state["operacoes_excluidas"] = novas_excluidas
            core.salvar_config_supabase(
                supabase_client.get_client(), "operacoes_excluidas", list(novas_excluidas)
            )
            st.session_state["sucesso_operacoes"] = True
            st.rerun()
        if st.button("↩️ Restaurar padrão (só Anestesia, fora Mário Covas/Amhemed)"):
            padrao = core.operacoes_excluidas_por_padrao(df_linhas)
            st.session_state["operacoes_excluidas"] = padrao
            core.salvar_config_supabase(supabase_client.get_client(), "operacoes_excluidas", list(padrao))
            st.rerun()
    else:
        st.caption("Somente leitura — edição é exclusiva do papel master.")
        st.dataframe(
            tabela_op.drop(columns=["chave_operacao"]), use_container_width=True, hide_index=True,
        )

    st.stop()

# ============================================================= PÁGINA: GESTORES
if pagina == "👔 Gestores":
    st.subheader("👔 Gestores — Nível 4 automático")
    st.caption(
        "Médicos marcados aqui entram automaticamente no Nível 4 (aumento no plantão + seguros) "
        "em TODO o histórico deles, mesmo sem bater o volume mínimo. Funciona **junto com** "
        "(não substitui) a detecção automática por pagamento de Coordenação/Gestão lançado na "
        "base — um médico vira Nível 4 se tiver qualquer uma das duas."
    )
    if st.session_state.pop("sucesso_gestores", False):
        st.success("Lista de gestores salva no Supabase e aplicada — histórico recalculado.")

    medicos_todos = core.listar_medicos(agg)
    if eh_master:
        selecionados = st.multiselect(
            "Médicos gestores",
            medicos_todos,
            default=sorted(st.session_state["medicos_gestores"] & set(medicos_todos)),
            help="Comece a digitar o nome para filtrar a lista.",
        )
        if st.button("✅ Aplicar e recalcular", type="primary"):
            st.session_state["medicos_gestores"] = set(selecionados)
            core.salvar_config_supabase(supabase_client.get_client(), "medicos_gestores", selecionados)
            st.session_state["sucesso_gestores"] = True
            st.rerun()
        if st.button("↩️ Limpar lista"):
            st.session_state["medicos_gestores"] = set()
            core.salvar_config_supabase(supabase_client.get_client(), "medicos_gestores", [])
            st.rerun()
    else:
        st.caption("Somente leitura — edição é exclusiva do papel master.")
        st.dataframe(
            pd.DataFrame({"Médico": sorted(st.session_state["medicos_gestores"])}),
            use_container_width=True, hide_index=True,
        )

    st.stop()

# ============================================================= PÁGINA: REGRAS DO PROGRAMA
if pagina == "⚙️ Regras do Programa":
    st.subheader("⚙️ Regras do Programa")
    st.caption(
        "Qualquer mudança aqui recalcula o histórico inteiro na hora — reflete direto no "
        "resultado das outras telas, para todo mundo que estiver usando o sistema."
    )
    if not eh_master:
        st.warning("Somente leitura — edição é exclusiva do papel master.")

    # ---------------------------------------------------------- NÍVEIS, CARÊNCIA, % AUMENTO
    st.markdown("#### Níveis, carência e % de aumento no plantão")
    st.caption(
        "A carência só segura os **benefícios extras** do nível (seguro a partir do Nível 3, "
        "cursos, licenças) — o **% de aumento no plantão** vale imediato, pelo volume do próprio "
        "mês, sem esperar carência (esclarecido pelo usuário, 2026-08-20)."
    )
    if st.session_state.pop("sucesso_config", False):
        st.success("Parâmetros salvos no Supabase e aplicados — histórico recalculado com as novas regras.")
    if st.session_state.pop("avisos_config", None):
        for a in st.session_state.get("_avisos_pendentes", []):
            st.warning(a)
        st.caption("Mesmo assim, os parâmetros foram salvos e recalculados — ajuste os limites se não era essa a intenção.")

    linhas_config = []
    for n in st.session_state["niveis_custom"]:
        linhas_config.append({
            "Nível": n["idx"],
            "Mín. plantões": n["min_plantoes"],
            "Máx. plantões (vazio = sem limite)": n["max_plantoes"],
            "Mín. FDS+Noturno": n["min_fds"],
            "Carência (meses)": n["carencia_meses"],
            "% aumento no plantão": round(n["pct_aumento"] * 100, 2),
        })
    df_config = pd.DataFrame(linhas_config).set_index("Nível")

    if eh_master:
        df_editado = st.data_editor(
            df_config, use_container_width=True, key="editor_niveis",
            column_config={
                "Máx. plantões (vazio = sem limite)": st.column_config.NumberColumn(
                    help="Deixe vazio no Nível 4 para representar '20 ou mais, sem teto'."
                ),
                "% aumento no plantão": st.column_config.NumberColumn(
                    help="Em %, ex.: 2.75 para 2,75%", format="%.2f",
                ),
            },
        )
        cbtn1, cbtn2 = st.columns(2)
        if cbtn1.button("✅ Aplicar", type="primary", key="btn_aplicar_niveis"):
            novos_niveis = []
            for idx, row in df_editado.iterrows():
                maximo = row["Máx. plantões (vazio = sem limite)"]
                novos_niveis.append({
                    "idx": int(idx),
                    "nome": f"Nível {int(idx)}",
                    "min_plantoes": int(row["Mín. plantões"]),
                    "max_plantoes": None if pd.isna(maximo) else int(maximo),
                    "min_fds": int(row["Mín. FDS+Noturno"]),
                    "carencia_meses": int(row["Carência (meses)"]),
                    "pct_aumento": float(row["% aumento no plantão"]) / 100,
                    "pct_exibido": round(float(row["% aumento no plantão"])),
                    "tem_seguro": int(idx) >= 3,
                })
            novos_niveis.sort(key=lambda n: n["idx"])
            avisos = []
            for i in range(len(novos_niveis) - 1):
                atual, prox = novos_niveis[i], novos_niveis[i + 1]
                maximo_atual = atual["max_plantoes"]
                if maximo_atual is None or maximo_atual + 1 != prox["min_plantoes"]:
                    avisos.append(
                        f"Entre Nível {atual['idx']} (máx. {maximo_atual}) e Nível {prox['idx']} "
                        f"(mín. {prox['min_plantoes']}) há uma lacuna ou sobreposição — médicos "
                        f"nesse intervalo vão cair no Nível 1 por padrão, sem aviso."
                    )
            st.session_state["_avisos_pendentes"] = avisos
            st.session_state["avisos_config"] = bool(avisos)
            st.session_state["sucesso_config"] = True
            st.session_state["niveis_custom"] = novos_niveis
            core.salvar_config_supabase(supabase_client.get_client(), "niveis_custom", novos_niveis)
            st.rerun()
        if cbtn2.button("↩️ Restaurar padrão", key="btn_restaurar_niveis"):
            padrao_niveis = copy.deepcopy(core.NIVEIS)
            st.session_state["niveis_custom"] = padrao_niveis
            core.salvar_config_supabase(supabase_client.get_client(), "niveis_custom", padrao_niveis)
            st.rerun()
        st.caption(
            "O recálculo roda o histórico inteiro de novo com as regras editadas (afeta "
            "carência e, portanto, todos os meses navegáveis, não só o mês selecionado)."
        )
    else:
        st.dataframe(df_config, use_container_width=True)

    # ---------------------------------------------------------- SEGUROS (N3+)
    st.markdown("---")
    st.markdown("#### Pacote de seguros (a partir do Nível 3)")
    if st.session_state.pop("sucesso_seguro", False):
        st.success("Custo do seguro salvo no Supabase e aplicado — histórico recalculado.")

    if eh_master:
        # Key do widget = mesmo nome da variavel de session_state (igual ao fix do "mes_atual") -
        # assim "Restaurar padrao" via on_click reseta o VALOR EXIBIDO tambem, nao so o numero
        # usado no calculo. Passar value= de novo nesses widgets nao adianta depois do primeiro
        # render (Streamlit ignora e mantem o que ja esta em session_state[key]).
        sc1, sc2 = st.columns(2)
        sc1.number_input(
            "Vida + DIT + Funeral (Porto Seguro), R$/médico/mês",
            min_value=0.0, step=1.0, format="%.2f", key="custo_seguro_vida_dit_funeral",
        )
        sc2.number_input(
            "RCP (Unimed Seguros), R$/médico/mês",
            min_value=0.0, step=1.0, format="%.2f", key="custo_seguro_rcp",
        )
        st.caption(
            f"Total atual: {fmt_brl(st.session_state['custo_seguro_vida_dit_funeral'] + st.session_state['custo_seguro_rcp'])}"
            f"/médico/mês (cobrado de todo médico Nível 3+)."
        )
        sbtn1, sbtn2 = st.columns(2)
        if sbtn1.button("✅ Aplicar", type="primary", key="btn_aplicar_seguro"):
            core.salvar_config_supabase(
                supabase_client.get_client(), "custo_seguro",
                {
                    "vida_dit_funeral": st.session_state["custo_seguro_vida_dit_funeral"],
                    "rcp": st.session_state["custo_seguro_rcp"],
                },
            )
            st.session_state["sucesso_seguro"] = True
            st.rerun()
        sbtn2.button("↩️ Restaurar padrão", key="btn_restaurar_seguro", on_click=_restaurar_seguro)
    else:
        st.metric(
            "Total por médico/mês",
            fmt_brl(st.session_state["custo_seguro_vida_dit_funeral"] + st.session_state["custo_seguro_rcp"]),
        )

    # ---------------------------------------------------------- BÔNUS RAMP-UP
    st.markdown("---")
    st.markdown("#### Bônus hospital em ramp-up")
    if st.session_state.pop("sucesso_rampup", False):
        st.success("Parâmetros do bônus de ramp-up salvos no Supabase e aplicados.")

    # "input_rampup_pct" guarda o % em unidade de exibicao (0-100), separado de "rampup_pct" (0-1,
    # usado direto no calculo do bonus) - por isso precisa de conversao no Aplicar, diferente do
    # seguro acima (mesma unidade nos dois lados).
    if "input_rampup_pct" not in st.session_state:
        st.session_state["input_rampup_pct"] = st.session_state["rampup_pct"] * 100
    if "input_rampup_duracao" not in st.session_state:
        st.session_state["input_rampup_duracao"] = st.session_state["rampup_duracao_meses"]

    if eh_master:
        rc1, rc2 = st.columns(2)
        rc1.number_input(
            "% fixo sobre o repasse do médico", min_value=0.0, max_value=100.0,
            step=0.5, format="%.2f", key="input_rampup_pct",
        )
        rc2.number_input(
            "Duração padrão (meses)", min_value=1, max_value=12,
            step=1, key="input_rampup_duracao",
        )
        st.caption(
            "O gatilho continua manual (tela Visão Geral, exclusivo do master) — isso só define "
            "o % e a duração padrão sugeridos quando o bônus for disparado."
        )
        rbtn1, rbtn2 = st.columns(2)
        if rbtn1.button("✅ Aplicar", type="primary", key="btn_aplicar_rampup"):
            st.session_state["rampup_pct"] = st.session_state["input_rampup_pct"] / 100
            st.session_state["rampup_duracao_meses"] = int(st.session_state["input_rampup_duracao"])
            core.salvar_config_supabase(
                supabase_client.get_client(), "rampup_params",
                {"pct": st.session_state["rampup_pct"], "duracao_meses": st.session_state["rampup_duracao_meses"]},
            )
            st.session_state["sucesso_rampup"] = True
            st.rerun()
        rbtn2.button(
            "↩️ Restaurar padrão (5%, 3 meses)", key="btn_restaurar_rampup", on_click=_restaurar_rampup
        )
    else:
        st.caption(
            f"{st.session_state['rampup_pct'] * 100:.2f}% sobre o repasse, por "
            f"{st.session_state['rampup_duracao_meses']} meses (padrão configurado pelo master)."
        )

    st.stop()

# ============================================================= PÁGINA: RELATÓRIO DO MÉDICO
if pagina == "📄 Relatório do Médico":
    st.subheader("📄 Relatório do Médico")
    st.caption(
        "Duas visões: **🖥️ Visão Sistema** (interna, com custo pago pela empresa e histórico "
        "completo) e **📋 Comunicado ao Médico** (versão limpa pronta pra entregar, com botão de PDF)."
    )

    medicos_lista_rel = sorted(niveis_df["medico"].unique())
    nome_rel = st.selectbox("Médico", [""] + medicos_lista_rel, key="relatorio_medico_nome")
    if not nome_rel:
        st.info("Selecione um médico para gerar o relatório.")
        st.stop()

    renderizar_relatorio_medico(nome_rel, st.session_state["mes_atual"])
    st.stop()

# ============================================================= PÁGINA: VISÃO GERAL

mes_ref = st.session_state["mes_atual"]
snap_completo = core.status_atual(niveis_df, anomes_referencia=mes_ref)
# "ativo no mes" = fez pelo menos 1 plantao naquele mes. snap_completo tambem carrega medicos com
# 0 plantoes no mes (preservados no historico so pra manter a carencia funcionando corretamente
# entre meses) - esses NAO contam como ativos nem entram nas contagens/tabela abaixo.
snap = snap_completo[snap_completo["n_plantoes"] >= 1]
if mes_ref != meses_disponiveis[-1]:
    st.info(f"Visualizando **{mes_ref}** (histórico) — não é o mês mais recente da base.")

# ---------------------------------------------------------------- VISÃO GERAL
st.subheader(f"Visão geral — {mes_ref}")

if "filtro_nivel_ms" not in st.session_state:
    st.session_state["filtro_nivel_ms"] = [2, 3, 4]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Médicos ativos no mês", len(snap))
if c1.button("Ver todos →", key="btn_total", use_container_width=True):
    st.session_state["filtro_nivel_ms"] = [1, 2, 3, 4]
    st.rerun()
for n, col in zip((1, 2, 3, 4), (c2, c3, c4, c5)):
    col.metric(f"Nível {n}", int((snap["nivel_bruto"] == n).sum()))
    if col.button("Ver lista →", key=f"btn_nivel_{n}", use_container_width=True):
        st.session_state["filtro_nivel_ms"] = [n]
        st.rerun()

st.markdown("#### Custo mensal projetado")
st.caption(
    "Aumento % no repasse já reflete o nível de pagamento (por volume, sem carência). Seguros só "
    "contam pros médicos que já cumpriram a carência do Nível 3+ (nível de benefícios) - ver "
    "coluna 'Faltam p/ próximo nível' na tabela abaixo pra quem ainda está no período de carência."
)
cc1, cc2, cc3, cc4 = st.columns(4)
cc1.metric("Seguros (N3+, benefícios liberados)", fmt_brl(snap["custo_seguro_mes"].sum()))
cc2.metric("Aumento % no repasse (pagamento)", fmt_brl(snap["custo_aumento_pct_mes"].sum()))
cc3.metric("Bônus ramp-up ativo", fmt_brl(snap["custo_rampup_mes"].sum()))
cc4.metric("Total", fmt_brl(
    snap["custo_seguro_mes"].sum() + snap["custo_aumento_pct_mes"].sum() + snap["custo_rampup_mes"].sum()
))

st.markdown("---")
st.markdown("#### Tabela de médicos")
st.caption(
    "FDS = Sáb/Dom. Noturno = a partir das 19h (ou marcado como Noturno/Cinderela). A exigência "
    "de cada nível soma FDS + Noturno (sem contar duas vezes o mesmo plantão)."
)
filtro_nivel = st.multiselect("Filtrar por nível", [1, 2, 3, 4], key="filtro_nivel_ms")
tabela = snap[snap["nivel_bruto"].isin(filtro_nivel)].sort_values(
    ["nivel_bruto", "n_plantoes"], ascending=[False, False]
)


def _resumo_faltam_proximo_nivel(row):
    """Texto compacto pra coluna 'Faltam p/ próximo nível' - pedido do usuário 2026-08-20, pra
    dar visibilidade direto na tabela (uso diário pelo escalista) de quanto falta pro médico subir,
    sem precisar abrir o relatório completo de cada um."""
    sim = core.simular_todos_niveis(row)
    if not sim:
        return "Nível máximo"
    prox = sim[0]
    partes = []
    if prox["faltam_plantoes"] > 0:
        partes.append(f"{prox['faltam_plantoes']} plantão(ões)")
    if prox["faltam_fds_ou_noturno"] > 0:
        partes.append(f"{prox['faltam_fds_ou_noturno']} FDS/Not.")
    if not partes:
        return f"N{prox['nivel_idx']} já sustentado (aguardando carência)"
    return f"N{prox['nivel_idx']}: +{' e +'.join(partes)}"


# Bug real encontrado ao vivo na auditoria (2026-08-20): com "Filtrar por nível" vazio (ninguém
# selecionado, ex.: clicando "Clear all"), tabela fica com 0 linhas - df.apply(func, axis=1) num
# DataFrame vazio devolve o próprio DataFrame (sem chamar func nenhuma vez, pandas não tem como
# inferir o formato de saída), não uma Series, e o .assign() quebrava com ValueError. Guarda
# explícita pro caso vazio em vez de deixar a tela inteira travar num erro.
if tabela.empty:
    tabela = tabela.assign(faltam_proximo_nivel=pd.Series(dtype="object"))
else:
    tabela = tabela.assign(faltam_proximo_nivel=tabela.apply(_resumo_faltam_proximo_nivel, axis=1))
st.caption("Clique numa linha pra abrir o relatório completo do médico logo abaixo.")
evento_tabela_medicos = st.dataframe(
    tabela[["medico", "n_plantoes", "n_fds", "n_noturno", "n_fds_ou_noturno", "nivel_bruto",
            "pct_aumento_exibido", "valor_repasse", "custo_aumento_pct_mes", "valor_total_geral",
            "faltam_proximo_nivel"]]
    .rename(columns={
        "medico": "Médico", "n_plantoes": "Total Plantões", "n_fds": "FDS (Sáb/Dom)",
        "n_noturno": "Noturno", "n_fds_ou_noturno": "FDS+Noturno (união)", "nivel_bruto": "Nível",
        "pct_aumento_exibido": "% Aumento", "valor_repasse": "Valor Plantões",
        "custo_aumento_pct_mes": "Valor Aumento", "valor_total_geral": "Total Geral",
        "faltam_proximo_nivel": "Faltam p/ próximo nível",
    })
    .style.format({"% Aumento": "{:.0f}%", "Valor Plantões": fmt_brl, "Valor Aumento": fmt_brl,
                    "Total Geral": fmt_brl}),
    use_container_width=True, hide_index=True,
    on_select="rerun", selection_mode="single-row", key="tabela_medicos_select",
)

# Linha selecionada na tabela acima -> mesmo relatorio completo (abas Sistema/Comunicado + PDF)
# que a pagina dedicada "📄 Relatório do Médico" mostra - pedido do usuario 2026-08-20, clicar no
# nome já abre tudo sem precisar trocar de página. Streamlit não tem "duplo-clique" nativo nessa
# tabela - um clique já seleciona a linha e dispara isso; clicar de novo na mesma linha desmarca.
linhas_selecionadas_medico = evento_tabela_medicos.selection.rows if evento_tabela_medicos else []
if linhas_selecionadas_medico:
    medico_clicado = tabela.iloc[linhas_selecionadas_medico[0]]["medico"]
    st.markdown("---")
    with st.container(border=True):
        st.markdown(f"### 📄 {medico_clicado}")
        renderizar_relatorio_medico(medico_clicado, mes_ref)

# ---------------------------------------------------------------- CONSULTA POR MÉDICO
st.markdown("---")
st.markdown("#### 🔍 Consultar médico específico")
medicos_lista = sorted(niveis_df["medico"].unique())
nome = st.selectbox("Nome completo", [""] + medicos_lista)
if nome:
    hist = niveis_df[niveis_df["medico"] == nome].sort_values("anomes")
    atual = hist.iloc[-1]
    nivel_pagamento_c = int(atual["nivel_bruto"])
    info_nivel_c = core.NIVEL_POR_IDX[nivel_pagamento_c]
    nivel_beneficios_c = int(atual["nivel_vestido"])
    tempo_nivel_c = atual["streak_nivel_bruto"]
    tempo_nivel_c = int(tempo_nivel_c) if pd.notna(tempo_nivel_c) else None
    meses_por_nivel_c = core.meses_por_nivel(hist)
    especialidades_c = df_linhas.loc[df_linhas["medico"] == nome, "especialidade"]
    especialidades_c = especialidades_c[especialidades_c != ""]
    moda_especialidade_c = especialidades_c.mode()
    especialidade_c = moda_especialidade_c.iat[0] if not moda_especialidade_c.empty else "—"

    st.markdown(
        f"##### {nome} &nbsp; "
        f"<span style='color:#6B7280;font-weight:400;font-size:0.75em'>{especialidade_c}</span>",
        unsafe_allow_html=True,
    )
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.markdown(f"**Nível vigente**<br>{badge_nivel(nivel_pagamento_c)}", unsafe_allow_html=True)
    m2.metric("Tempo de casa", f"{len(hist)} mês(es)", help=f"Desde {hist['anomes'].min()}")
    m3.metric(
        "Tempo no nível atual",
        f"{tempo_nivel_c} mês(es)" if tempo_nivel_c is not None else "—",
    )
    m4.metric("Total de plantões", int(atual["n_plantoes"]))
    m5.metric("FDS + Noturno", int(atual["n_fds_ou_noturno"]))
    m6.metric("Aumento no valor do plantão", f"{info_nivel_c['pct_exibido']}%")

    st.caption(
        "Meses em cada nível (histórico completo): "
        f"Nível 1: {meses_por_nivel_c[1]} · Nível 2: {meses_por_nivel_c[2]} · "
        f"Nível 3: {meses_por_nivel_c[3]} · Nível 4: {meses_por_nivel_c[4]}."
    )

    if nivel_pagamento_c != nivel_beneficios_c:
        carencia_necessaria_c = core.NIVEL_POR_IDX[nivel_pagamento_c]["carencia_meses"]
        st.info(
            f"O pagamento já está no **Nível {nivel_pagamento_c}** ({info_nivel_c['pct_exibido']}% "
            f"de aumento) — não espera carência. Mas os **benefícios extras** desse nível (seguro, "
            f"cursos, licenças) só liberam depois de **{carencia_necessaria_c} mês(es) consecutivos** "
            f"nesse volume; hoje os benefícios ativos ainda são os do **Nível {nivel_beneficios_c}**."
        )

    # Simulação "quanto falta pra cada nível acima" (pedido do usuário, 2026-08-20) - função
    # compartilhada com renderizar_relatorio_medico, ver renderizar_simulacao_niveis().
    renderizar_simulacao_niveis(atual)

    with st.expander("Ver histórico completo"):
        st.dataframe(
            hist[["anomes", "n_plantoes", "n_fds", "n_noturno", "nivel_bruto", "nivel_vestido"]]
            .rename(columns={"anomes": "Mês", "n_plantoes": "Plantões", "n_fds": "FDS (Sáb/Dom)",
                              "n_noturno": "Noturno", "nivel_bruto": "Nível (pagamento)",
                              "nivel_vestido": "Nível (benefícios)"}),
            use_container_width=True, hide_index=True,
        )

# ---------------------------------------------------------------- RAMP-UP (SÓ MASTER)
st.markdown("---")
st.markdown("#### 🚀 Bônus hospital em ramp-up")
rampup_pct = st.session_state["rampup_pct"]
rampup_duracao = st.session_state["rampup_duracao_meses"]
st.caption(
    f"Gatilho manual — {rampup_pct * 100:.2f}% fixo sobre o repasse do período, por "
    f"{rampup_duracao} meses a partir do disparo (ajustável em ⚙️ Regras do Programa)."
)
if not eh_master:
    st.warning(
        f"Disparo de bônus é exclusivo do papel **master**. Seu papel é **{usuario['papel']}** — "
        f"você pode simular o custo abaixo, mas não pode confirmar o disparo real."
    )

disparos_existentes = st.session_state["rampup_disparos"]
if not disparos_existentes.empty:
    with st.expander(f"📋 Disparos já confirmados ({len(disparos_existentes)})"):
        st.dataframe(
            disparos_existentes.assign(
                meses=disparos_existentes["meses"].apply(lambda m: ", ".join(sorted(m))),
                pct=disparos_existentes["pct"].apply(lambda p: f"{p * 100:.2f}%"),
            )[["operacao", "pct", "meses", "disparado_por", "disparado_em"]]
            .rename(columns={
                "operacao": "Hospital/Operação", "pct": "%", "meses": "Meses",
                "disparado_por": "Disparado por", "disparado_em": "Quando",
            }),
            use_container_width=True, hide_index=True,
        )

hospitais_disponiveis = sorted(df_linhas["operacao"].unique())
hosp_sel = st.selectbox("Hospital/operação em ramp-up", [""] + hospitais_disponiveis)
if hosp_sel:
    # So o repasse que CONTA pro nivel (mesmo escopo que calcular_rampup_por_medico_mes usa de
    # verdade pra aplicar o bonus) - preview tem que bater com o que realmente vai ser aplicado,
    # senao o master ve um numero no preview e outro depois de confirmar (achado real na
    # auditoria de 2026-08-20, quando o botao nem persistia nada ainda).
    janela = df_linhas[(df_linhas["operacao"] == hosp_sel) & (df_linhas["conta_pro_nivel"])]
    meses_disp = sorted(janela["anomes"].unique(), reverse=True)[:6]
    meses_sel = st.multiselect(
        f"Meses do ramp-up (padrão: {rampup_duracao} meses seguidos)",
        meses_disp, default=meses_disp[:rampup_duracao],
    )
    if meses_sel:
        repasse_periodo = janela[janela["anomes"].isin(meses_sel)]["valor"].sum()
        st.metric(f"Bônus de {rampup_pct * 100:.2f}% sobre o repasse ({hosp_sel}, {len(meses_sel)} meses)",
                  fmt_brl(repasse_periodo * rampup_pct))
        st.caption(f"Repasse total no período de referência (só plantões que contam pro nível): {fmt_brl(repasse_periodo)}")
        if eh_master:
            if st.button("✅ Confirmar disparo do bônus"):
                core.salvar_rampup_supabase(
                    supabase_client.get_client(), hosp_sel, rampup_pct, meses_sel, usuario["nome"]
                )
                st.session_state["rampup_disparos"] = core.consultar_rampup_supabase(
                    supabase_client.get_client()
                )
                st.success(
                    f"Disparado por {usuario['nome']}: {hosp_sel}, {rampup_pct * 100:.2f}% sobre "
                    f"{len(meses_sel)} meses ({fmt_brl(repasse_periodo * rampup_pct)} no período de "
                    "referência). Salvo no Supabase — já entra no Total Geral de cada médico "
                    "atendido nesses meses."
                )
                st.rerun()
