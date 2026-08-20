"""Programa Fidelidade CallMed (Constelação) - sistema interno, uso exclusivo do time
administrativo (médicos não têm acesso - decisão do usuário, sessão 2026-08-18).

Papéis: master (Luiz - único que pode disparar o bônus de hospital em ramp-up, ação com custo
real), gestor e analista (veem tudo, não disparam ações sensíveis).

Aviso de segurança: login por e-mail + senha em texto puro, sem hash, sem recuperação de senha.
Serve pra identificar quem é quem dentro de um grupo pequeno e confiável (3 pessoas do time adm),
NÃO é proteção contra acesso mal intencionado. Antes de considerar isso "seguro de verdade",
trocar as senhas em usuarios.py e, se for para produção real, migrar para algo como a versão
Lovable já discutida.
"""
import copy
import datetime as dt
import json
import os

import streamlit as st
import pandas as pd
import core
import config_caminhos as cfg
import usuarios
import comunicado_pdf

st.set_page_config(page_title="Programa Fidelidade CallMed", page_icon="⭐", layout="wide")


@st.cache_data(ttl=3600, show_spinner="Lendo base de plantões (Excel)...")
def carregar_linhas_brutas():
    """Parte lenta (leitura do Excel) - nao depende de operacoes nem de niveis, so precisa rodar
    de novo se o Excel mudar."""
    return core.carregar_plantoes()


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


def badge_nivel(n):
    cores = {1: "#9CA3AF", 2: "#60A5FA", 3: "#A78BFA", 4: "#FBBF24"}
    return f'<span style="background:{cores.get(n,"#999")};color:#111;padding:2px 10px;border-radius:12px;font-weight:600;">Nível {n}</span>'


# ---------------------------------------------------------------- LOGIN
if "usuario" not in st.session_state:
    st.title("⭐ Programa Fidelidade CallMed — Constelação")
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

if "niveis_custom" not in st.session_state:
    st.session_state["niveis_custom"] = copy.deepcopy(core.NIVEIS)

df_linhas = carregar_linhas_brutas()
if "operacoes_excluidas" not in st.session_state:
    st.session_state["operacoes_excluidas"] = core.operacoes_excluidas_por_padrao(df_linhas)
if "medicos_gestores" not in st.session_state:
    st.session_state["medicos_gestores"] = set()
if "custo_seguro_vida_dit_funeral" not in st.session_state:
    st.session_state["custo_seguro_vida_dit_funeral"] = core.CUSTO_SEGURO_VIDA_DIT_FUNERAL
if "custo_seguro_rcp" not in st.session_state:
    st.session_state["custo_seguro_rcp"] = core.CUSTO_RCP
if "rampup_pct" not in st.session_state:
    st.session_state["rampup_pct"] = 0.05
if "rampup_duracao_meses" not in st.session_state:
    st.session_state["rampup_duracao_meses"] = 3

agg = agregar_com_operacoes(df_linhas, tuple(sorted(st.session_state["operacoes_excluidas"])))
niveis_df = calcular_niveis_cached(
    agg, niveis_para_json(st.session_state["niveis_custom"]),
    tuple(sorted(st.session_state["medicos_gestores"])),
    st.session_state["custo_seguro_vida_dit_funeral"] + st.session_state["custo_seguro_rcp"],
)
if niveis_df.empty:
    st.error("Base de plantões não encontrada ou vazia. Verifique o caminho em config_caminhos.py.")
    st.stop()

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


def _restaurar_rampup():
    st.session_state["input_rampup_pct"] = 5.0
    st.session_state["input_rampup_duracao"] = 3
    st.session_state["rampup_pct"] = 0.05
    st.session_state["rampup_duracao_meses"] = 3


with st.sidebar:
    st.markdown(f"**{usuario['nome']}**")
    st.caption(f"Papel: {usuario['papel']}")
    if st.button("Sair"):
        del st.session_state["usuario"]
        st.rerun()
    st.markdown("---")
    pagina = st.radio(
        "Navegação",
        ["📊 Visão Geral", "🏥 Operações", "👔 Gestores", "⚙️ Regras do Programa",
         "📄 Relatório do Médico"],
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

    # ---------------------------------------------------------- FONTE DE DADOS (upload)
    with st.expander("📁 Fonte de dados (base de plantões)", expanded=False):
        usando_upload = os.path.exists(cfg.UPLOAD_PLANTOES)
        if usando_upload:
            ts = dt.datetime.fromtimestamp(os.path.getmtime(cfg.UPLOAD_PLANTOES))
            st.caption(f"Usando arquivo enviado em {ts.strftime('%d/%m/%Y %H:%M')}.")
        else:
            st.caption(f"Usando caminho local (só funciona rodando na máquina com OneDrive sincronizado).")

        if eh_master:
            novo_arquivo = st.file_uploader(
                "Enviar novo Excel de plantões (mesmo formato da aba 'BD')", type=["xlsx"]
            )
            if novo_arquivo is not None:
                if st.button("📤 Confirmar envio e recarregar"):
                    os.makedirs(cfg.UPLOAD_DIR, exist_ok=True)
                    with open(cfg.UPLOAD_PLANTOES, "wb") as f:
                        f.write(novo_arquivo.getbuffer())
                    carregar_linhas_brutas.clear()
                    agregar_com_operacoes.clear()
                    calcular_niveis_cached.clear()
                    st.success("Arquivo salvo — recarregando com os dados novos.")
                    st.rerun()
        else:
            st.caption("Envio de novo arquivo é exclusivo do papel master.")

st.title("⭐ Programa Fidelidade CallMed — Constelação")
st.caption(f"Regras vigentes a partir de {core.GO_LIVE} · dados até {niveis_df['anomes'].max()}")

# ============================================================= PÁGINA: OPERAÇÕES
if pagina == "🏥 Operações":
    st.subheader("🏥 Operações que contam pro Programa Fidelidade")
    st.caption(
        "Cada linha é uma combinação **hospital + especialidade** — ex.: 'Hospital São Bernardo' "
        "vira 3 linhas (Anestesia, Enfermaria, UTI), cada uma flegável separadamente. Desmarcar "
        "uma linha tira só aqueles plantões da contagem de nível dos médicos — afeta o histórico "
        "inteiro, não só o mês atual."
    )
    if st.session_state.pop("sucesso_operacoes", False):
        st.success("Lista de operações aplicada — histórico recalculado.")

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
                help="Desmarque para excluir essa combinação hospital+especialidade do Programa Fidelidade."
            )},
        )
        if st.button("✅ Aplicar mudanças e recalcular", type="primary"):
            # "chave_operacao" fica no dataframe (so nao aparece na tela, via column_order) pra
            # ler de volta aqui de forma robusta, sem depender da ordem das linhas.
            novas_excluidas = set(
                tabela_editada.loc[~tabela_editada["Incluída"], "chave_operacao"]
            )
            st.session_state["operacoes_excluidas"] = novas_excluidas
            st.session_state["sucesso_operacoes"] = True
            st.rerun()
        if st.button("↩️ Restaurar padrão (só Anestesia, fora Mário Covas/Amhemed)"):
            st.session_state["operacoes_excluidas"] = core.operacoes_excluidas_por_padrao(df_linhas)
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
        st.success("Lista de gestores aplicada — histórico recalculado.")

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
            st.session_state["sucesso_gestores"] = True
            st.rerun()
        if st.button("↩️ Limpar lista"):
            st.session_state["medicos_gestores"] = set()
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
    if st.session_state.pop("sucesso_config", False):
        st.success("Parâmetros aplicados — histórico recalculado com as novas regras.")
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
            st.rerun()
        if cbtn2.button("↩️ Restaurar padrão", key="btn_restaurar_niveis"):
            st.session_state["niveis_custom"] = copy.deepcopy(core.NIVEIS)
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
        st.success("Custo do seguro aplicado — histórico recalculado.")

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
        st.success("Parâmetros do bônus de ramp-up aplicados.")

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

    mes_relatorio = st.session_state["mes_atual"]
    hist_rel = niveis_df[niveis_df["medico"] == nome_rel].sort_values("anomes")
    if mes_relatorio in hist_rel["anomes"].values:
        atual_rel = hist_rel[hist_rel["anomes"] == mes_relatorio].iloc[0]
    else:
        atual_rel = hist_rel.iloc[-1]
        st.warning(
            f"Sem dado em {mes_relatorio} pra esse médico — mostrando o último mês disponível "
            f"({atual_rel['anomes']})."
        )

    nivel_vestido_rel = int(atual_rel["nivel_vestido"])
    info_nivel_rel = core.NIVEL_POR_IDX[nivel_vestido_rel]
    tempo_nivel_rel = core.tempo_no_nivel_atual(atual_rel)
    prox_info_rel = core.proximo_nivel_info(atual_rel)
    primeiro_mes_rel = hist_rel["anomes"].min()
    # hist_rel ja tem 1 linha por mes desde o primeiro plantao do medico ate o mes mais recente da
    # base inteira (meses sem plantao viram linha com 0, pra carencia funcionar certo - ver
    # calcular_niveis) - entao len(hist_rel) e literalmente "quantos meses de casa", sem gap.
    tempo_de_casa_rel = len(hist_rel)

    aba_sistema, aba_medico = st.tabs(["🖥️ Visão Sistema", "📋 Comunicado ao Médico"])

    # ---------------------------------------------------------- ABA SISTEMA (interna)
    with aba_sistema:
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(f"**Nível vigente**<br>{badge_nivel(nivel_vestido_rel)}", unsafe_allow_html=True)
        m2.metric("Tempo de casa", f"{tempo_de_casa_rel} mês(es)", help=f"Desde {primeiro_mes_rel}")
        m3.metric(
            "Tempo no nível atual",
            f"{tempo_nivel_rel} mês(es)" if tempo_nivel_rel is not None else "—",
        )
        m4.metric("Aumento no plantão", f"{info_nivel_rel['pct_exibido']}%")

        st.markdown(f"#### Plantões em {mes_relatorio}")
        plantoes_mes_rel = df_linhas[
            (df_linhas["medico"] == nome_rel) & (df_linhas["anomes"] == mes_relatorio)
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
                    "n_noturno": "Noturno", "nivel_bruto": "Nível (volume)",
                    "nivel_vestido": "Nível (vigente)", "valor_repasse": "Valor Plantões",
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
            f"### Nível {nivel_vestido_rel} — {info_nivel_rel['pct_exibido']}% de aumento no plantão"
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Plantões no mês", int(atual_rel["n_plantoes"]))
        c2.metric("FDS/Noturno", int(atual_rel["n_fds_ou_noturno"]))
        c3.metric(
            "Tempo no nível", f"{tempo_nivel_rel} mês(es)" if tempo_nivel_rel is not None else "—",
        )

        st.markdown("##### Benefícios inclusos")
        for beneficio in core.beneficios_acumulados(nivel_vestido_rel):
            st.markdown(f"- {beneficio}")

        if prox_info_rel:
            partes_rel = []
            if prox_info_rel["faltam_plantoes"] > 0:
                partes_rel.append(f"{prox_info_rel['faltam_plantoes']} plantão(ões)")
            if prox_info_rel["faltam_fds_ou_noturno"] > 0:
                partes_rel.append(f"{prox_info_rel['faltam_fds_ou_noturno']} plantão(ões) de FDS/noturno")
            if partes_rel:
                st.info(f"Faltam {' e '.join(partes_rel)} no mês pro {prox_info_rel['proximo_nivel']}.")
            else:
                st.info(
                    f"O volume deste mês já sustenta o {prox_info_rel['proximo_nivel']} — o "
                    "benefício passa a valer após a carência, se mantido nos próximos meses."
                )

        pdf_bytes_rel = comunicado_pdf.gerar_pdf_comunicado(
            nome_medico=nome_rel, mes_ref=mes_relatorio, nivel_vestido=nivel_vestido_rel,
            n_plantoes=int(atual_rel["n_plantoes"]), n_fds=int(atual_rel["n_fds"]),
            n_noturno=int(atual_rel["n_noturno"]), pct_aumento_exibido=info_nivel_rel["pct_exibido"],
            tempo_no_nivel=tempo_nivel_rel, proximo_nivel_info=prox_info_rel,
        )
        st.download_button(
            "📄 Baixar PDF para o médico", data=pdf_bytes_rel,
            file_name=f"comunicado_{nome_rel.replace(' ', '_')}_{mes_relatorio}.pdf",
            mime="application/pdf", type="primary",
        )

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
    col.metric(f"Nível {n}", int((snap["nivel_vestido"] == n).sum()))
    if col.button("Ver lista →", key=f"btn_nivel_{n}", use_container_width=True):
        st.session_state["filtro_nivel_ms"] = [n]
        st.rerun()

st.markdown("#### Custo mensal projetado (nível vestido atual)")
cc1, cc2, cc3 = st.columns(3)
cc1.metric("Seguros (N3+)", fmt_brl(snap["custo_seguro_mes"].sum()))
cc2.metric("Aumento % no repasse", fmt_brl(snap["custo_aumento_pct_mes"].sum()))
cc3.metric("Total", fmt_brl(snap["custo_seguro_mes"].sum() + snap["custo_aumento_pct_mes"].sum()))

st.markdown("---")
st.markdown("#### Tabela de médicos")
st.caption(
    "FDS = Sáb/Dom. Noturno = a partir das 19h (ou marcado como Noturno/Cinderela). A exigência "
    "de cada nível soma FDS + Noturno (sem contar duas vezes o mesmo plantão)."
)
filtro_nivel = st.multiselect("Filtrar por nível", [1, 2, 3, 4], key="filtro_nivel_ms")
tabela = snap[snap["nivel_vestido"].isin(filtro_nivel)].sort_values(
    ["nivel_vestido", "n_plantoes"], ascending=[False, False]
)
st.dataframe(
    tabela[["medico", "n_plantoes", "n_fds", "n_noturno", "nivel_vestido",
            "pct_aumento_exibido", "valor_repasse", "custo_aumento_pct_mes", "valor_total_geral"]]
    .rename(columns={
        "medico": "Médico", "n_plantoes": "Total Plantões", "n_fds": "FDS (Sáb/Dom)",
        "n_noturno": "Noturno", "nivel_vestido": "Nível",
        "pct_aumento_exibido": "% Aumento", "valor_repasse": "Valor Plantões",
        "custo_aumento_pct_mes": "Valor Aumento", "valor_total_geral": "Total Geral",
    })
    .style.format({"% Aumento": "{:.0f}%", "Valor Plantões": fmt_brl, "Valor Aumento": fmt_brl,
                    "Total Geral": fmt_brl}),
    use_container_width=True, hide_index=True,
)

# ---------------------------------------------------------------- CONSULTA POR MÉDICO
st.markdown("---")
st.markdown("#### 🔍 Consultar médico específico")
medicos_lista = sorted(niveis_df["medico"].unique())
nome = st.selectbox("Nome completo", [""] + medicos_lista)
if nome:
    hist = niveis_df[niveis_df["medico"] == nome].sort_values("anomes")
    atual = hist.iloc[-1]
    info_nivel = core.NIVEL_POR_IDX[int(atual["nivel_vestido"])]

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.markdown(f"**Nível vigente**<br>{badge_nivel(int(atual['nivel_vestido']))}", unsafe_allow_html=True)
    m2.metric("Total de plantões", int(atual["n_plantoes"]))
    m3.metric("FDS (Sáb/Dom)", int(atual["n_fds"]))
    m4.metric("Noturno", int(atual["n_noturno"]))
    m5.metric("Aumento no valor do plantão", f"{info_nivel['pct_exibido']}%")

    if int(atual["nivel_bruto"]) != int(atual["nivel_vestido"]):
        st.info(
            f"O volume deste mês já sustenta o **Nível {atual['nivel_bruto']}**, mas o benefício "
            f"elevado só passa a valer depois da carência (meses seguidos mantendo o critério). "
            f"Hoje está com o **Nível {atual['nivel_vestido']}** ativo."
        )

    with st.expander("Ver histórico completo"):
        st.dataframe(
            hist[["anomes", "n_plantoes", "n_fds", "n_noturno", "nivel_bruto", "nivel_vestido"]]
            .rename(columns={"anomes": "Mês", "n_plantoes": "Plantões", "n_fds": "FDS (Sáb/Dom)",
                              "n_noturno": "Noturno", "nivel_bruto": "Nível (volume)",
                              "nivel_vestido": "Nível (vigente)"}),
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

hospitais_disponiveis = sorted(df_linhas["operacao"].unique())
hosp_sel = st.selectbox("Hospital/operação em ramp-up", [""] + hospitais_disponiveis)
if hosp_sel:
    janela = df_linhas[df_linhas["operacao"] == hosp_sel]
    meses_disp = sorted(janela["anomes"].unique(), reverse=True)[:6]
    meses_sel = st.multiselect(
        f"Meses do ramp-up (padrão: {rampup_duracao} meses seguidos)",
        meses_disp, default=meses_disp[:rampup_duracao],
    )
    if meses_sel:
        repasse_periodo = janela[janela["anomes"].isin(meses_sel)]["valor"].sum()
        st.metric(f"Bônus de {rampup_pct * 100:.2f}% sobre o repasse ({hosp_sel}, {len(meses_sel)} meses)",
                  fmt_brl(repasse_periodo * rampup_pct))
        st.caption(f"Repasse total no período de referência: {fmt_brl(repasse_periodo)}")
        if eh_master:
            if st.button("✅ Confirmar disparo do bônus"):
                st.success(
                    f"Disparado por {usuario['nome']} ({mes_ref}): {hosp_sel}, "
                    f"{fmt_brl(repasse_periodo * rampup_pct)} sobre {len(meses_sel)} meses. "
                    f"(Registro apenas nesta sessão - ainda não persiste em arquivo.)"
                )
