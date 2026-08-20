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

st.set_page_config(page_title="Programa Fidelidade CallMed", page_icon="⭐", layout="wide")


@st.cache_data(ttl=3600, show_spinner="Lendo base de plantões (Excel)...")
def carregar_agregado():
    """Parte lenta (leitura do Excel) - nao depende dos parametros de nivel, so precisa rodar de
    novo se o Excel mudar."""
    return core.montar_agregado()


@st.cache_data(ttl=3600, show_spinner=False)
def carregar_linhas_brutas():
    return core.carregar_plantoes()


@st.cache_data(ttl=3600, show_spinner="Recalculando níveis com os parâmetros atuais...")
def calcular_niveis_cached(agg, niveis_json):
    """Cacheado pelo JSON dos parametros - so recalcula de fato quando os parametros mudam."""
    niveis = json.loads(niveis_json)
    return core.calcular_niveis(agg, niveis=niveis)


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

agg = carregar_agregado()
niveis_df = calcular_niveis_cached(agg, niveis_para_json(st.session_state["niveis_custom"]))
if niveis_df.empty:
    st.error("Base de plantões não encontrada ou vazia. Verifique o caminho em config_caminhos.py.")
    st.stop()

col_titulo, col_user = st.columns([4, 1])
with col_titulo:
    st.title("⭐ Programa Fidelidade CallMed — Constelação")
    st.caption(f"Regras vigentes a partir de {core.GO_LIVE} · dados até {niveis_df['anomes'].max()}")
with col_user:
    st.markdown(f"**{usuario['nome']}**")
    st.caption(f"Papel: {usuario['papel']}")
    if st.button("Sair"):
        del st.session_state["usuario"]
        st.rerun()

# ---------------------------------------------------------------- FONTE DE DADOS (upload)
with st.expander("📁 Fonte de dados (base de plantões)", expanded=False):
    usando_upload = os.path.exists(cfg.UPLOAD_PLANTOES)
    if usando_upload:
        ts = dt.datetime.fromtimestamp(os.path.getmtime(cfg.UPLOAD_PLANTOES))
        st.caption(f"Usando arquivo enviado em {ts.strftime('%d/%m/%Y %H:%M')}.")
    else:
        st.caption(f"Usando caminho local: `{cfg.BASE_PLANTOES}` (só funciona rodando na máquina com OneDrive sincronizado).")

    if eh_master:
        novo_arquivo = st.file_uploader(
            "Enviar novo Excel de plantões (mesmo formato da aba 'BD')", type=["xlsx"]
        )
        if novo_arquivo is not None:
            if st.button("📤 Confirmar envio e recarregar"):
                os.makedirs(cfg.UPLOAD_DIR, exist_ok=True)
                with open(cfg.UPLOAD_PLANTOES, "wb") as f:
                    f.write(novo_arquivo.getbuffer())
                carregar_agregado.clear()
                carregar_linhas_brutas.clear()
                calcular_niveis_cached.clear()
                st.success("Arquivo salvo — recarregando com os dados novos.")
                st.rerun()
    else:
        st.caption("Envio de novo arquivo é exclusivo do papel master.")

# ---------------------------------------------------------------- CONFIGURAÇÕES DO PROGRAMA
_tem_mensagem_pendente = st.session_state.get("sucesso_config", False)
with st.expander(
    "⚙️ Configurações do programa (níveis, carência, % de aumento)",
    expanded=_tem_mensagem_pendente,
):
    if not eh_master:
        st.caption("Somente leitura — edição é exclusiva do papel master.")

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
            "Mín. FDS": n["min_fds"],
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
        if cbtn1.button("✅ Aplicar mudanças e recalcular", type="primary"):
            novos_niveis = []
            for idx, row in df_editado.iterrows():
                maximo = row["Máx. plantões (vazio = sem limite)"]
                novos_niveis.append({
                    "idx": int(idx),
                    "nome": f"Nível {int(idx)}",
                    "min_plantoes": int(row["Mín. plantões"]),
                    "max_plantoes": None if pd.isna(maximo) else int(maximo),
                    "min_fds": int(row["Mín. FDS"]),
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
        if cbtn2.button("↩️ Restaurar padrão aprovado"):
            st.session_state["niveis_custom"] = copy.deepcopy(core.NIVEIS)
            st.rerun()
        st.caption(
            "O recálculo roda o histórico inteiro de novo com as regras editadas (afeta carência "
            "e, portanto, todos os meses navegáveis abaixo, não só o mês selecionado)."
        )
    else:
        st.dataframe(df_config, use_container_width=True)

meses_disponiveis = sorted(niveis_df["anomes"].unique())
# Se um upload de Excel novo mudou o intervalo de meses disponivel (ex.: arquivo mais curto), o
# mes que estava selecionado antes pode nao existir mais na lista nova - sem esse fallback, o
# .index() abaixo quebra o app com ValueError.
if (
    "mes_selecionado" not in st.session_state
    or st.session_state["mes_selecionado"] not in meses_disponiveis
):
    st.session_state["mes_selecionado"] = meses_disponiveis[-1]

mcol1, mcol2, mcol3 = st.columns([1, 3, 1])
idx_atual = meses_disponiveis.index(st.session_state["mes_selecionado"])
with mcol1:
    if st.button("← Mês anterior", disabled=(idx_atual == 0), use_container_width=True):
        st.session_state["mes_selecionado"] = meses_disponiveis[idx_atual - 1]
        st.rerun()
with mcol2:
    mes_escolhido = st.select_slider(
        "Navegar por mês", options=meses_disponiveis,
        value=st.session_state["mes_selecionado"], key="slider_mes", label_visibility="collapsed",
    )
    if mes_escolhido != st.session_state["mes_selecionado"]:
        st.session_state["mes_selecionado"] = mes_escolhido
        st.rerun()
with mcol3:
    if st.button("Mês seguinte →", disabled=(idx_atual == len(meses_disponiveis) - 1), use_container_width=True):
        st.session_state["mes_selecionado"] = meses_disponiveis[idx_atual + 1]
        st.rerun()

mes_ref = st.session_state["mes_selecionado"]
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
filtro_nivel = st.multiselect("Filtrar por nível", [1, 2, 3, 4], key="filtro_nivel_ms")
tabela = snap[snap["nivel_vestido"].isin(filtro_nivel)].sort_values(
    ["nivel_vestido", "n_plantoes"], ascending=[False, False]
)
st.dataframe(
    tabela[["medico", "n_plantoes", "n_fds", "teve_coordenacao", "nivel_bruto", "nivel_vestido",
            "custo_seguro_mes", "custo_aumento_pct_mes"]]
    .rename(columns={"medico": "Médico", "n_plantoes": "Plantões", "n_fds": "FDS",
                      "teve_coordenacao": "Coordenador", "nivel_bruto": "Nível (volume)",
                      "nivel_vestido": "Nível (vigente)", "custo_seguro_mes": "Custo seguro",
                      "custo_aumento_pct_mes": "Custo % aumento"}),
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

    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f"**Nível vigente**<br>{badge_nivel(int(atual['nivel_vestido']))}", unsafe_allow_html=True)
    m2.metric("Plantões válidos no mês", int(atual["n_plantoes"]))
    m3.metric("Plantões em Sex/Sáb/Dom", int(atual["n_fds"]))
    m4.metric("Aumento no valor do plantão", f"{info_nivel['pct_exibido']}%")

    if int(atual["nivel_bruto"]) != int(atual["nivel_vestido"]):
        st.info(
            f"O volume deste mês já sustenta o **Nível {atual['nivel_bruto']}**, mas o benefício "
            f"elevado só passa a valer depois da carência (meses seguidos mantendo o critério). "
            f"Hoje está com o **Nível {atual['nivel_vestido']}** ativo."
        )

    with st.expander("Ver histórico completo"):
        st.dataframe(
            hist[["anomes", "n_plantoes", "n_fds", "nivel_bruto", "nivel_vestido"]]
            .rename(columns={"anomes": "Mês", "n_plantoes": "Plantões", "n_fds": "Fim de semana",
                              "nivel_bruto": "Nível (volume)", "nivel_vestido": "Nível (vigente)"}),
            use_container_width=True, hide_index=True,
        )

# ---------------------------------------------------------------- RAMP-UP (SÓ MASTER)
st.markdown("---")
st.markdown("#### 🚀 Bônus hospital em ramp-up")
st.caption(
    "Gatilho manual — 5% fixo sobre o repasse do período, por 3 meses a partir do disparo."
)
if not eh_master:
    st.warning(
        f"Disparo de bônus é exclusivo do papel **master**. Seu papel é **{usuario['papel']}** — "
        f"você pode simular o custo abaixo, mas não pode confirmar o disparo real."
    )

df_raw_hosp = carregar_linhas_brutas()
hospitais_disponiveis = sorted(
    df_raw_hosp["local"].str.rsplit(" - ", n=1).str[0].str.strip().unique()
)
hosp_sel = st.selectbox("Hospital/operação em ramp-up", [""] + hospitais_disponiveis)
if hosp_sel:
    janela = df_raw_hosp[df_raw_hosp["local"].str.startswith(hosp_sel, na=False)]
    meses_disp = sorted(janela["anomes"].unique(), reverse=True)[:6]
    meses_sel = st.multiselect("Meses do ramp-up (normalmente 3 meses seguidos)", meses_disp, default=meses_disp[:3])
    if meses_sel:
        repasse_periodo = janela[janela["anomes"].isin(meses_sel)]["valor"].sum()
        st.metric(f"Bônus de 5% sobre o repasse ({hosp_sel}, {len(meses_sel)} meses)",
                  fmt_brl(repasse_periodo * 0.05))
        st.caption(f"Repasse total no período de referência: {fmt_brl(repasse_periodo)}")
        if eh_master:
            if st.button("✅ Confirmar disparo do bônus"):
                st.success(
                    f"Disparado por {usuario['nome']} ({mes_ref}): {hosp_sel}, "
                    f"{fmt_brl(repasse_periodo * 0.05)} sobre {len(meses_sel)} meses. "
                    f"(Registro apenas nesta sessão - ainda não persiste em arquivo.)"
                )
