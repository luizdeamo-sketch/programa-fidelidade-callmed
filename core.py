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
    # min_fds = minimo de FDS(Sab/Dom) + Noturno somados (uniao) - valores confirmados pelo
    # usuario em 2026-08-20 (exemplo real: medico com 19 plantoes precisa de min. 4).
    {"idx": 1, "nome": "Nível 1", "min_plantoes": 1, "max_plantoes": 9, "min_fds": 0,
     "carencia_meses": 0, "pct_aumento": 0.0, "pct_exibido": 0, "tem_seguro": False},
    {"idx": 2, "nome": "Nível 2", "min_plantoes": 10, "max_plantoes": 14, "min_fds": 3,
     "carencia_meses": 1, "pct_aumento": 0.0275, "pct_exibido": 3, "tem_seguro": False},
    {"idx": 3, "nome": "Nível 3", "min_plantoes": 15, "max_plantoes": 19, "min_fds": 4,
     "carencia_meses": 3, "pct_aumento": 0.0375, "pct_exibido": 4, "tem_seguro": True},
    {"idx": 4, "nome": "Nível 4", "min_plantoes": 20, "max_plantoes": None, "min_fds": 5,
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
    # FDS = Sabado e Domingo (sexta NAO conta mais - mudanca de regra confirmada pelo usuario,
    # sessao 2026-08-20, ver Programa_Constelacao_CallMed_v2.md).
    df["eh_fds"] = df["data_dt"].dt.dayofweek.isin([5, 6]).fillna(False)
    # Noturno = comeca as 19h ou depois, OU esta marcado como Noturno/Cinderela no Tipo/Local
    # (mesma sessao) - cobre casos com esse rotulo mas horario de inicio um pouco antes das 19h.
    texto_tipo_local = (df["tipo"].fillna("") + " " + df["local"].fillna("")).str.lower()
    df["eh_noturno"] = (
        (df["data_dt"].dt.hour >= 19).fillna(False)
        | texto_tipo_local.str.contains("noturno|cinderela", regex=True, na=False)
    )
    # Exigencia de nivel (min_fds) passa a valer sobre a UNIAO de FDS e Noturno, sem contar 2x um
    # plantao que seja os dois (ex.: sexta a noite - sexta ja nao conta como FDS pela regra nova,
    # mas se fosse sabado a noite contaria 1 vez so aqui).
    df["eh_fds_ou_noturno"] = df["eh_fds"] | df["eh_noturno"]
    df["eh_gestao"] = df["tipo"].isin(GESTAO_TIPOS)
    df["operacao"] = df["local"].apply(operacao_de)
    df["hospital_excluido"] = df["local"].str.contains(EXCLUSAO_HOSPITAL_REGEX, na=False)
    df["eh_anestesia"] = df["especialidade"] == ESPECIALIDADE_VALIDA
    # plantao valido = conta pro volume do nivel: especialidade Anestesia, hospital nao excluido,
    # e nao e pagamento de gestao/coordenacao (isso conta separado, pra flag de coordenador). Este
    # e o padrao default (regex fixo) - a tela "Operacoes" permite substituir hospital_excluido por
    # uma lista customizada via aplicar_operacoes_customizadas(), sem precisar reler o Excel.
    df["conta_pro_nivel"] = df["eh_anestesia"] & (~df["hospital_excluido"]) & (~df["eh_gestao"])
    return df


def operacao_de(local):
    """Extrai o nome da 'operacao' (hospital/grupo) de um campo Local - mesmo criterio usado no
    seletor de ramp-up: remove so o ultimo segmento (turno/sub-unidade), ex.: 'Hospital Ana Costa
    - Centro Cirurgico' -> 'Hospital Ana Costa'."""
    return str(local or "").rsplit(" - ", 1)[0].strip()


def listar_operacoes(df):
    """Lista as operacoes distintas encontradas na base, com contexto (especialidades vistas,
    total de linhas, quantas contam hoje pela regra padrao) - usada pela tela de Configuracoes >
    Operacoes, pra o master validar/ajustar manualmente o que entra no Programa Fidelidade."""
    if df.empty:
        return pd.DataFrame(columns=["operacao", "total_linhas", "especialidades", "conta_hoje", "incluida_padrao"])
    resumo = df.groupby("operacao").agg(
        total_linhas=("valor", "count"),
        especialidades=("especialidade", lambda s: ", ".join(sorted(set(s) - {""}))),
        conta_hoje=("conta_pro_nivel", "sum"),
    ).reset_index()
    resumo["incluida_padrao"] = resumo["conta_hoje"] > 0
    return resumo.sort_values("total_linhas", ascending=False)


def operacoes_excluidas_por_padrao(df):
    """Calcula o conjunto de operacoes que o filtro padrao (EXCLUSAO_HOSPITAL_REGEX) excluiria -
    usado so pra inicializar a tela de Configuracoes > Operacoes com o estado atual, antes do
    master customizar qualquer coisa."""
    if df.empty:
        return set()
    return set(df.loc[df["hospital_excluido"], "operacao"].unique())


def aplicar_operacoes_customizadas(df, operacoes_excluidas):
    """Recalcula conta_pro_nivel usando uma lista customizada de operacoes excluidas (definida na
    tela de Configuracoes > Operacoes) em vez do EXCLUSAO_HOSPITAL_REGEX fixo. Nao mexe no Excel,
    so reprocessa o dataframe ja carregado - barato, pode rodar a cada mudanca na tela."""
    df = df.copy()
    operacoes_excluidas = set(operacoes_excluidas or [])
    df["operacao_excluida"] = df["operacao"].isin(operacoes_excluidas)
    df["conta_pro_nivel"] = df["eh_anestesia"] & (~df["operacao_excluida"]) & (~df["eh_gestao"])
    return df


def agregar_mensal(df):
    """Agrega linha-a-linha em (medico, anomes) -> n_plantoes validos, n_fds (Sab/Dom) validos,
    n_noturno validos, n_fds_ou_noturno (uniao, base da exigencia de nivel), se teve pagamento de
    coordenacao/gestao naquele mes (mesmo fora do escopo de hospital - coordenacao e coordenacao
    em qualquer lugar), e valor de repasse elegivel (base pro % de aumento)."""
    colunas_vazias = ["medico", "anomes", "n_plantoes", "n_fds", "n_noturno", "n_fds_ou_noturno",
                       "teve_coordenacao", "valor_repasse"]
    if df.empty:
        return pd.DataFrame(columns=colunas_vazias)
    validos = df[df["conta_pro_nivel"]]
    agg = validos.groupby(["medico", "anomes"]).agg(
        n_plantoes=("valor", "count"),
        n_fds=("eh_fds", "sum"),
        n_noturno=("eh_noturno", "sum"),
        n_fds_ou_noturno=("eh_fds_ou_noturno", "sum"),
        valor_repasse=("valor", "sum"),
    ).reset_index()
    coord = df[df["eh_gestao"]].groupby(["medico", "anomes"]).size().reset_index(name="_n_coord")
    agg = agg.merge(coord, on=["medico", "anomes"], how="outer")
    # medicos que so tem linha de coordenacao (sem plantao clinico contavel no mes) tambem entram
    for col in ("n_plantoes", "n_fds", "n_noturno", "n_fds_ou_noturno"):
        agg[col] = agg[col].fillna(0).astype(int)
    agg["valor_repasse"] = agg["valor_repasse"].fillna(0.0)
    agg["teve_coordenacao"] = agg["_n_coord"].fillna(0) > 0
    agg = agg.drop(columns=["_n_coord"])
    return agg


def listar_medicos(agg):
    """Lista de medicos distintos na base agregada, ordenada - usada pelo seletor da tela de
    Gestores (marcar manualmente quem entra direto no Nivel 4, sem depender do pagamento de
    Coordenacao/Gestao ter sido lancado certo na base)."""
    if agg.empty:
        return []
    return sorted(agg["medico"].unique())


def calcular_niveis(agg, niveis=None, medicos_gestores=None):
    """Para cada medico, percorre cronologicamente os meses (desde o primeiro mes dele na base
    ate o mes mais recente) e calcula nivel_bruto, nivel_vestido (com carencia aplicada) e os
    custos do mes. Meses sem nenhuma linha pro medico dentro da janela viram 0 plantoes (reseta
    carencia de nivel 2+, mas nao "sai" do historico).

    'niveis' permite recalcular com parametros customizados (editados na tela de Configuracoes)
    em vez dos parametros padrao aprovados (NIVEIS) - mesmo formato de lista de dicts.

    'medicos_gestores' e a lista curada manualmente na tela "Gestores" (nomes de medico) - quem
    esta nela tem Nivel 4 automatico em TODO o historico, junto com (nao substitui, conforme
    decisao do usuario em 2026-08-20) a deteccao automatica via pagamento de Coordenacao/Gestao
    (teve_coordenacao). Existe pra cobrir gestor que nunca teve um pagamento desse tipo lancado
    certo na base."""
    niveis = sorted(niveis or NIVEIS, key=lambda n: n["idx"])
    nivel_por_idx = niveis_para_dict(niveis)
    medicos_gestores = set(medicos_gestores or [])
    if agg.empty:
        return pd.DataFrame()
    meses_todos = sorted(agg["anomes"].unique())
    mes_para_indice = {m: i for i, m in enumerate(meses_todos)}

    resultados = []
    for medico, grp in agg.groupby("medico"):
        eh_gestor_manual = medico in medicos_gestores
        grp = grp.set_index("anomes")
        primeiro_idx = min(mes_para_indice[m] for m in grp.index)
        ultimo_idx = mes_para_indice[meses_todos[-1]]  # roda ate o fim da base pra todo mundo
        streaks = {2: 0, 3: 0, 4: 0}
        for i in range(primeiro_idx, ultimo_idx + 1):
            am = meses_todos[i]
            if am in grp.index:
                row = grp.loc[am]
                n_plantoes = int(row["n_plantoes"])
                n_fds, n_noturno = int(row["n_fds"]), int(row["n_noturno"])
                n_fds_ou_noturno = int(row["n_fds_ou_noturno"])
                teve_coord = bool(row["teve_coordenacao"])
                valor_repasse = float(row["valor_repasse"])
            else:
                n_plantoes, n_fds, n_noturno, n_fds_ou_noturno = 0, 0, 0, 0
                teve_coord, valor_repasse = False, 0.0

            # exigencia de nivel (min_fds) conta sobre a UNIAO fds+noturno, nao so fds puro.
            # Nivel 4 automatico se teve pagamento de coordenacao/gestao naquele mes OU se esta
            # na lista manual de gestores (as duas coexistem - OR, decisao do usuario 2026-08-20).
            nivel_bruto = (
                niveis[-1]["idx"] if (teve_coord or eh_gestor_manual)
                else _nivel_bruto(n_plantoes, n_fds_ou_noturno, niveis)
            )

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
            valor_total_geral = valor_repasse + custo_aumento_pct

            resultados.append({
                "medico": medico, "anomes": am,
                "n_plantoes": n_plantoes, "n_fds": n_fds, "n_noturno": n_noturno,
                "n_fds_ou_noturno": n_fds_ou_noturno, "teve_coordenacao": teve_coord,
                "valor_repasse": valor_repasse,
                "nivel_bruto": nivel_bruto, "nivel_vestido": nivel_vestido,
                "pct_aumento_exibido": info_vestido["pct_exibido"],
                "streak_n2": streaks[2], "streak_n3": streaks[3], "streak_n4": streaks[4],
                "custo_seguro_mes": custo_seguro, "custo_aumento_pct_mes": custo_aumento_pct,
                "valor_total_geral": valor_total_geral,
            })
    return pd.DataFrame(resultados)


def montar_agregado(arquivo=None):
    """Le + agrega (a parte lenta: leitura do Excel). Nao depende dos parametros de nivel, entao
    fica cacheavel separado - so precisa rodar de novo se o Excel mudar, nao se as regras
    mudarem na tela de Configuracoes."""
    df_linhas = carregar_plantoes(arquivo)
    return agregar_mensal(df_linhas)


def montar_base_completa(arquivo=None, niveis=None, medicos_gestores=None):
    """Pipeline completo: le, agrega, calcula niveis. Cacheable pela camada de UI."""
    agg = montar_agregado(arquivo)
    return calcular_niveis(agg, niveis=niveis, medicos_gestores=medicos_gestores)


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
