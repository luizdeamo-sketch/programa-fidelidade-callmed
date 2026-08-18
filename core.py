"""
Motor de dados do Programa Fidelidade CallMed (Constelação) - versao 2, vigente a partir de
Setembro/2026.

Regras implementadas (ver Programa_Constelacao_CallMed_v2.md na raiz do projeto para o
documento de referencia completo, aprovado pelo usuario):

- 4 niveis por medico, mensal, por volume de plantoes clinicos validos (exclui Coordenacao/
  Gestao/ASSIST.ADM do volume, exclui hospitais fora do escopo e tipos de unidade fora do
  escopo - ver EXCLUSAO_HOSPITAIS/EXCLUSAO_LOCAL_REGEX).
- Carencia: meses CONSECUTIVOS cumprindo o criterio do nivel antes do beneficio comecar a valer
  (formula: carencia_meses[nivel] + 1 meses seguidos == beneficio ativo). Se o medico cai do
  nivel em qualquer mes da janela, o contador daquele nivel reseta.
- Coordenadores (qualquer mes com pagamento tipo Coordenacao/Gestao) tem Nivel 4 automatico
  naquele mes, sem precisar de volume nem carencia.
- Backfill: o sistema calcula o historico completo desde o inicio da base ate o mes mais
  recente, entao em Setembro/2026 (GO_LIVE) cada medico ja "nasce" no nivel/carencia real que
  o historico dele sustenta - ninguem comeca do zero por definicao de codigo.
"""
import re
from collections import defaultdict
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook

import config_caminhos as cfg

GO_LIVE = "2026-09"

PLACEHOLDERS_MEDICO = {"<Sem Responsável>", "Admin CallmedCall", ".CallMed Adm"}
GESTAO_TIPOS = {"Coordenação", "Gestão", "ASSIST. ADM"}

# Hospitais inteiros fora do escopo do programa (qualquer plantao la, de qualquer tipo)
EXCLUSAO_HOSPITAL_REGEX = re.compile(r"covas|amhemed", re.IGNORECASE)
# Escopo do programa = "todas as operacoes de ANESTESIA" (confirmado pelo usuario). A base nova
# (BD Pantoes .../1.ANALISES LUIZ) tem uma coluna "Especialidade" que ja classifica cada linha
# nesse nivel (Anestesia/Enfermaria/UTI/Adm/CallMed/Ambulatorio/Oftalto/...) - usar isso em vez de
# tentar adivinhar UTI/Enfermaria por regex no campo Local (que era fragil, mesmo tipo de
# problema ja visto com a contaminacao do grupo "HSH"). So "Anestesia" conta pro nivel; isso ja
# exclui UTI e Enfermaria automaticamente, sem precisar de regra separada pra elas.
ESPECIALIDADE_VALIDA = "Anestesia"

NIVEIS = [
    {"idx": 1, "nome": "Nível 1", "min_plantoes": 1, "max_plantoes": 9, "min_fds": 0,
     "carencia_meses": 0, "pct_aumento": 0.0, "pct_exibido": 0, "tem_seguro": False},
    {"idx": 2, "nome": "Nível 2", "min_plantoes": 10, "max_plantoes": 14, "min_fds": 1,
     "carencia_meses": 1, "pct_aumento": 0.0275, "pct_exibido": 3, "tem_seguro": False},
    {"idx": 3, "nome": "Nível 3", "min_plantoes": 15, "max_plantoes": 19, "min_fds": 2,
     "carencia_meses": 3, "pct_aumento": 0.0375, "pct_exibido": 4, "tem_seguro": True},
    {"idx": 4, "nome": "Nível 4", "min_plantoes": 20, "max_plantoes": None, "min_fds": 2,
     "carencia_meses": 6, "pct_aumento": 0.045, "pct_exibido": 5, "tem_seguro": True},
]
NIVEL_POR_IDX = {n["idx"]: n for n in NIVEIS}

# Custos reais confirmados por apolice (Porto Seguro + Unimed Seguros), por medico/mes, a partir
# do Nivel 3 (onde o seguro entra no programa).
CUSTO_SEGURO_VIDA_DIT_FUNERAL = 185.61  # Porto Seguro: Vida (99k/198k) + DIT (166,66/dia) + Funeral (10k)
CUSTO_RCP = 117.60  # Unimed Seguros: RCP 100k, franquia zero
CUSTO_SEGURO_TOTAL_MES = CUSTO_SEGURO_VIDA_DIT_FUNERAL + CUSTO_RCP  # R$303,21


def _nivel_bruto(n_plantoes, n_fds, niveis=None):
    """Nivel que o volume/fds do mes sustenta, sem considerar carencia nem coordenacao."""
    niveis = niveis or NIVEIS
    nivel = 1
    for n in niveis:
        maximo = n["max_plantoes"] if n["max_plantoes"] is not None else float("inf")
        if n["min_plantoes"] <= n_plantoes <= maximo and n_fds >= n["min_fds"]:
            nivel = n["idx"]
    return nivel


def niveis_para_dict(niveis=None):
    return {n["idx"]: n for n in (niveis or NIVEIS)}


def carregar_plantoes(arquivo=None):
    """Le a base BD de plantoes (aba 'BD', formato "1.ANALISES LUIZ": colunas deslocadas +1 em
    relacao ao arquivo antigo do Desktop, com a coluna extra 'Especialidade' no fim) e retorna
    DataFrame linha-a-linha com os flags de elegibilidade ja calculados (nao agregado ainda)."""
    arquivo = arquivo or cfg.resolver_base_plantoes()
    wb = load_workbook(arquivo, data_only=True, read_only=True)
    ws = wb["BD"]
    rows_iter = ws.iter_rows(values_only=True)
    next(rows_iter)
    linhas = []
    for row in rows_iter:
        mes, ano, data_raw, local = row[3], row[4], row[5], row[7]
        medico, tipo, valor = row[10], row[11], row[12]
        especialidade = row[18] if len(row) > 18 else None
        if not isinstance(mes, (int, float)) or not isinstance(ano, (int, float)):
            continue
        if not isinstance(valor, (int, float)) or valor <= 0:
            continue
        if not medico or medico in PLACEHOLDERS_MEDICO:
            continue
        local_s = str(local or "")
        linhas.append({
            "anomes": f"{int(ano)}-{int(mes):02d}",
            "medico": str(medico).strip(),
            "data_raw": data_raw,
            "local": local_s,
            "tipo": str(tipo or ""),
            "especialidade": str(especialidade or ""),
            "valor": float(valor),
        })
    wb.close()
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    df["data_dt"] = pd.to_datetime(df["data_raw"], dayfirst=True, errors="coerce")
    df["eh_fds"] = df["data_dt"].dt.dayofweek.isin([4, 5, 6]).fillna(False)
    df["eh_gestao"] = df["tipo"].isin(GESTAO_TIPOS)
    df["hospital_excluido"] = df["local"].str.contains(EXCLUSAO_HOSPITAL_REGEX, na=False)
    df["eh_anestesia"] = df["especialidade"] == ESPECIALIDADE_VALIDA
    # plantao valido = conta pro volume do nivel: especialidade Anestesia, hospital nao excluido,
    # e nao e pagamento de gestao/coordenacao (isso conta separado, pra flag de coordenador)
    df["conta_pro_nivel"] = df["eh_anestesia"] & (~df["hospital_excluido"]) & (~df["eh_gestao"])
    return df


def agregar_mensal(df):
    """Agrega linha-a-linha em (medico, anomes) -> n_plantoes validos, n_fds validos, se teve
    pagamento de coordenacao/gestao naquele mes (mesmo fora do escopo de hospital - coordenacao
    e coordenacao em qualquer lugar), e valor de repasse elegivel (base pro % de aumento)."""
    if df.empty:
        return pd.DataFrame(columns=["medico", "anomes", "n_plantoes", "n_fds", "teve_coordenacao", "valor_repasse"])
    validos = df[df["conta_pro_nivel"]]
    agg = validos.groupby(["medico", "anomes"]).agg(
        n_plantoes=("valor", "count"),
        n_fds=("eh_fds", "sum"),
        valor_repasse=("valor", "sum"),
    ).reset_index()
    coord = df[df["eh_gestao"]].groupby(["medico", "anomes"]).size().reset_index(name="_n_coord")
    agg = agg.merge(coord, on=["medico", "anomes"], how="outer")
    # medicos que so tem linha de coordenacao (sem plantao clinico contavel no mes) tambem entram
    agg["n_plantoes"] = agg["n_plantoes"].fillna(0).astype(int)
    agg["n_fds"] = agg["n_fds"].fillna(0).astype(int)
    agg["valor_repasse"] = agg["valor_repasse"].fillna(0.0)
    agg["teve_coordenacao"] = agg["_n_coord"].fillna(0) > 0
    agg = agg.drop(columns=["_n_coord"])
    return agg


def calcular_niveis(agg, niveis=None):
    """Para cada medico, percorre cronologicamente os meses (desde o primeiro mes dele na base
    ate o mes mais recente) e calcula nivel_bruto, nivel_vestido (com carencia aplicada) e os
    custos do mes. Meses sem nenhuma linha pro medico dentro da janela viram 0 plantoes (reseta
    carencia de nivel 2+, mas nao "sai" do historico).

    'niveis' permite recalcular com parametros customizados (editados na tela de Configuracoes)
    em vez dos parametros padrao aprovados (NIVEIS) - mesmo formato de lista de dicts."""
    niveis = niveis or NIVEIS
    nivel_por_idx = niveis_para_dict(niveis)
    if agg.empty:
        return pd.DataFrame()
    meses_todos = sorted(agg["anomes"].unique())
    mes_para_indice = {m: i for i, m in enumerate(meses_todos)}

    resultados = []
    for medico, grp in agg.groupby("medico"):
        grp = grp.set_index("anomes")
        primeiro_idx = min(mes_para_indice[m] for m in grp.index)
        ultimo_idx = max(mes_para_indice[m] for m in meses_todos if meses_todos.index(m) <= mes_para_indice[max(grp.index)])
        ultimo_idx = mes_para_indice[meses_todos[-1]]  # roda ate o fim da base pra todo mundo
        streaks = {2: 0, 3: 0, 4: 0}
        for i in range(primeiro_idx, ultimo_idx + 1):
            am = meses_todos[i]
            if am in grp.index:
                row = grp.loc[am]
                n_plantoes, n_fds = int(row["n_plantoes"]), int(row["n_fds"])
                teve_coord = bool(row["teve_coordenacao"])
                valor_repasse = float(row["valor_repasse"])
            else:
                n_plantoes, n_fds, teve_coord, valor_repasse = 0, 0, False, 0.0

            nivel_bruto = niveis[-1]["idx"] if teve_coord else _nivel_bruto(n_plantoes, n_fds, niveis)

            for nivel_check in (2, 3, 4):
                if nivel_bruto >= nivel_check:
                    streaks[nivel_check] += 1
                else:
                    streaks[nivel_check] = 0

            nivel_vestido = 1
            for nivel_check in (2, 3, 4):
                carencia = nivel_por_idx[nivel_check]["carencia_meses"]
                if streaks[nivel_check] >= carencia + 1:
                    nivel_vestido = nivel_check

            info_vestido = nivel_por_idx[nivel_vestido]
            custo_seguro = CUSTO_SEGURO_TOTAL_MES if info_vestido["tem_seguro"] else 0.0
            custo_aumento_pct = valor_repasse * info_vestido["pct_aumento"]

            resultados.append({
                "medico": medico, "anomes": am,
                "n_plantoes": n_plantoes, "n_fds": n_fds, "teve_coordenacao": teve_coord,
                "valor_repasse": valor_repasse,
                "nivel_bruto": nivel_bruto, "nivel_vestido": nivel_vestido,
                "streak_n2": streaks[2], "streak_n3": streaks[3], "streak_n4": streaks[4],
                "custo_seguro_mes": custo_seguro, "custo_aumento_pct_mes": custo_aumento_pct,
            })
    return pd.DataFrame(resultados)


def montar_agregado(arquivo=None):
    """Le + agrega (a parte lenta: leitura do Excel). Nao depende dos parametros de nivel, entao
    fica cacheavel separado - so precisa rodar de novo se o Excel mudar, nao se as regras
    mudarem na tela de Configuracoes."""
    df_linhas = carregar_plantoes(arquivo)
    return agregar_mensal(df_linhas)


def montar_base_completa(arquivo=None, niveis=None):
    """Pipeline completo: le, agrega, calcula niveis. Cacheable pela camada de UI."""
    agg = montar_agregado(arquivo)
    return calcular_niveis(agg, niveis=niveis)


def status_atual(niveis_df, anomes_referencia=None):
    """Snapshot do mes mais recente disponivel (ou anomes_referencia se passado) por medico."""
    if niveis_df.empty:
        return niveis_df
    am = anomes_referencia or niveis_df["anomes"].max()
    return niveis_df[niveis_df["anomes"] == am].copy()


def proximo_nivel_info(row):
    """Dado um snapshot-row de status_atual, calcula quanto falta pro proximo nivel (por
    volume - carencia adicional continua sendo tempo, nao da pra "comprar")."""
    nivel_atual = row["nivel_bruto"]
    if nivel_atual >= 4:
        return None
    prox = NIVEL_POR_IDX[nivel_atual + 1]
    faltam_plantoes = max(0, prox["min_plantoes"] - row["n_plantoes"])
    faltam_fds = max(0, prox["min_fds"] - row["n_fds"])
    return {"proximo_nivel": prox["nome"], "faltam_plantoes": faltam_plantoes, "faltam_fds": faltam_fds}
