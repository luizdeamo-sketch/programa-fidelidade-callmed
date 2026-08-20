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

# Tipos de pagamento que NAO sao plantao clinico novo - bonus/premiacao/adiantamento de um plantao
# que ja tem sua propria linha com Tipo normal em algum lugar. Achado na auditoria de 2026-08-20:
# "Antecipacao" bate com o proprio beneficio documentado do programa ("antecipacao de valores de
# plantao, pago ate 2 dias apos o plantao" - Nivel 1), ou seja, e o MESMO plantao pago cedo, nao
# um plantao a mais. "Callmed Premium" bate com o nome do proprio programa (pagamento do premio de
# fidelidade entrando como linha de "plantao"). Confirmado pelo usuario: excluir da contagem de
# volume/nivel E do valor de repasse (base do % de aumento) - sem isso o medico recebe % de
# aumento em cima do proprio bonus, e o plantao original conta 2x.
# "Bonificacao" e "Gratificacao" ficaram FORA dessa lista (removidas em 2026-08-20, mesmo dia):
# usuario confirmou que sao pagamento por plantao MAIOR que o normal ou por participacao em algo
# atipico da rotina - ou seja, plantao de verdade, so com valor diferenciado. Contam normalmente.
TIPOS_NAO_CONTAM_VOLUME = {
    "Antecipação", "Callmed Premium", "Premiação Infiniti",
    ".Quatro Estrelas CallMed", ".Três Estrelas CallMed", ".Duas Estrelas CallMed",
}

# Hospitais inteiros fora do escopo do programa (qualquer plantao la, de qualquer tipo)
EXCLUSAO_HOSPITAL_REGEX = re.compile(r"covas|amhemed", re.IGNORECASE)
# Escopo do programa = "todas as operacoes de ANESTESIA" (confirmado pelo usuario). A base nova
# (BD Pantoes .../1.ANALISES LUIZ) tem uma coluna "Especialidade" que ja classifica cada linha
# nesse nivel (Anestesia/Enfermaria/UTI/Adm/CallMed/Ambulatorio/Oftalto/...) - usar isso em vez de
# tentar adivinhar UTI/Enfermaria por regex no campo Local (que era fragil, mesmo tipo de
# problema ja visto com a contaminacao do grupo "HSH"). So "Anestesia" conta pro nivel; isso ja
# exclui UTI e Enfermaria automaticamente, sem precisar de regra separada pra elas.
ESPECIALIDADE_VALIDA = "Anestesia"

# Limiar (%) de linhas NAO-Anestesia numa operacao pra considera-la "dominante em anestesia" -
# achado na auditoria de 2026-08-20 (pedido do usuario): varias operacoes que sao Anestesia quase
# pura (Mario Covas 6,23%, Ana Costa 0-3,45%, Santa Helena 0-1,61%, etc.) tem uma pontinha de
# linhas Enfermaria/UTI que o usuario confirmou ser ERRO DE CLASSIFICACAO no relatorio (a
# operacao so faz Anestesia de verdade). A distribuicao real tem um gap enorme e limpo: as
# operacoes "sujas por erro" ficam todas abaixo de ~7% de linhas nao-Anestesia, e as operacoes que
# SAO de verdade multi-especialidade (Sao Bernardo, Notre UTI, Prevent, etc.) ficam todas acima de
# ~67% - 10% fica bem no meio dessa folga, sem risco de pegar operacao genuinamente mista.
LIMIAR_PCT_OUTRAS_OPERACAO_ANESTESIA = 10.0

# Separador da chave composta operacao+especialidade usada na tela "Operacoes" (ex.: "Hospital
# Sao Bernardo :: Anestesia") - precisa ser algo que nao apareca em nome de hospital nem de
# especialidade real da base.
SEP_OP_ESP = " :: "

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
    df["eh_tipo_nao_clinico"] = df["tipo"].isin(TIPOS_NAO_CONTAM_VOLUME)
    df["operacao"] = df["local"].apply(operacao_de)
    df["hospital_excluido"] = df["local"].str.contains(EXCLUSAO_HOSPITAL_REGEX, na=False)

    # Correcao de erro de classificacao (auditoria 2026-08-20, regra dada pelo usuario): se uma
    # operacao e dominante em Anestesia (poucas linhas Enfermaria/UTI perdidas no meio - a
    # operacao "so faz Anestesia" na pratica), trata essas linhas minoritarias como Anestesia
    # tambem, porque o mais provavel e que vieram com a especialidade errada no relatorio. So se
    # aplica a Enfermaria/UTI (o que o usuario citou) - Adm/Ambulatorio minoritarios continuam
    # como estao, sao outra natureza de linha (normalmente pagamento administrativo mesmo).
    contagem_por_operacao = df.groupby("operacao")["especialidade"].value_counts().unstack(fill_value=0)
    total_por_operacao = contagem_por_operacao.sum(axis=1)
    anestesia_por_operacao = contagem_por_operacao.get(ESPECIALIDADE_VALIDA, 0)
    pct_outras_por_operacao = (total_por_operacao - anestesia_por_operacao) / total_por_operacao * 100
    operacoes_dominantes_anestesia = set(
        pct_outras_por_operacao[pct_outras_por_operacao < LIMIAR_PCT_OUTRAS_OPERACAO_ANESTESIA].index
    )
    eh_operacao_dominante_anestesia = df["operacao"].isin(operacoes_dominantes_anestesia)
    eh_provavel_erro_especialidade = eh_operacao_dominante_anestesia & df["especialidade"].isin(
        {"Enfermaria", "UTI"}
    )
    # "especialidade_efetiva" = especialidade real, exceto pelas linhas corrigidas acima - e o que
    # o resto do pipeline (eh_anestesia, chave_operacao, listar_operacoes) usa a partir daqui,
    # nunca a coluna "especialidade" crua.
    df["especialidade_efetiva"] = df["especialidade"].where(
        ~eh_provavel_erro_especialidade, ESPECIALIDADE_VALIDA
    )
    df["eh_anestesia"] = df["especialidade_efetiva"] == ESPECIALIDADE_VALIDA
    # "chave_operacao" = operacao (hospital/grupo) + especialidade efetiva, ex.: "Hospital Sao
    # Bernardo :: Anestesia" - granularidade real da tela "Operacoes" (decisao do usuario em
    # 2026-08-20: um hospital com Anestesia/Enfermaria/UTI vira ate 3 linhas flegaveis
    # separadamente, nao 1 so - exceto quando a correcao acima ja juntou tudo em Anestesia).
    especialidade_disp = df["especialidade_efetiva"].replace("", "(sem especialidade)")
    df["chave_operacao"] = df["operacao"] + SEP_OP_ESP + especialidade_disp
    # plantao valido = conta pro volume do nivel: especialidade Anestesia, hospital nao excluido,
    # e nao e pagamento de gestao/coordenacao (isso conta separado, pra flag de coordenador). Este
    # e o padrao default (regex fixo, so Anestesia) - a tela "Operacoes" permite substituir esse
    # filtro por uma lista customizada de chave_operacao via aplicar_operacoes_customizadas(),
    # sem precisar reler o Excel - inclusive liberando especialidades fora de Anestesia se o
    # master decidir flegar.
    df["conta_pro_nivel"] = (
        df["eh_anestesia"] & (~df["hospital_excluido"]) & (~df["eh_gestao"])
        & (~df["eh_tipo_nao_clinico"])
    )
    return df


def operacao_de(local):
    """Extrai o nome da 'operacao' (hospital/grupo) de um campo Local - mesmo criterio usado no
    seletor de ramp-up: remove so o ultimo segmento (turno/sub-unidade), ex.: 'Hospital Ana Costa
    - Centro Cirurgico' -> 'Hospital Ana Costa'."""
    return str(local or "").rsplit(" - ", 1)[0].strip()


def listar_operacoes(df):
    """Lista as combinacoes distintas de (operacao, especialidade EFETIVA) encontradas na base -
    cada uma e uma linha flegavel separada na tela de Configuracoes > Operacoes (ex.: 'Hospital
    Sao Bernardo' com Anestesia/Enfermaria/UTI vira 3 linhas, nao 1 com 'especialidades vistas'
    numa lista - decisao do usuario em 2026-08-20, pra poder incluir/excluir cada combinacao por
    si). Usa especialidade_efetiva (nao a crua) - operacoes dominantes em Anestesia com
    Enfermaria/UTI minoritarios ja aparecem com tudo junto como uma linha so de Anestesia (a
    correcao de erro de classificacao ja rodou em carregar_plantoes)."""
    colunas_vazias = ["chave_operacao", "operacao", "especialidade", "total_linhas", "conta_hoje",
                       "incluida_padrao"]
    if df.empty:
        return pd.DataFrame(columns=colunas_vazias)
    resumo = df.groupby(["chave_operacao", "operacao", "especialidade_efetiva"]).agg(
        total_linhas=("valor", "count"),
        conta_hoje=("conta_pro_nivel", "sum"),
    ).reset_index().rename(columns={"especialidade_efetiva": "especialidade"})
    resumo["especialidade"] = resumo["especialidade"].replace("", "(sem especialidade)")
    resumo["incluida_padrao"] = resumo["conta_hoje"] > 0
    return resumo.sort_values(["operacao", "especialidade"])


def operacoes_excluidas_por_padrao(df):
    """Calcula o conjunto de chaves (operacao+especialidade) que o filtro padrao excluiria hoje:
    so Anestesia conta, e dentro disso ainda exclui os hospitais do EXCLUSAO_HOSPITAL_REGEX -
    usado so pra inicializar a tela de Configuracoes > Operacoes com um estado EQUIVALENTE ao
    comportamento anterior ao refinamento por especialidade, antes do master customizar."""
    if df.empty:
        return set()
    elegivel_padrao = df["eh_anestesia"] & (~df["hospital_excluido"])
    return set(df.loc[~elegivel_padrao, "chave_operacao"].unique())


def aplicar_operacoes_customizadas(df, operacoes_excluidas):
    """Recalcula conta_pro_nivel usando um conjunto customizado de chaves (operacao+especialidade)
    excluidas (tela de Configuracoes > Operacoes) em vez do filtro fixo (so Anestesia, fora
    EXCLUSAO_HOSPITAL_REGEX). Granularidade agora e por combinacao especifica, entao o master pode
    liberar uma especialidade fora de Anestesia se quiser (ela so nao aparece pre-marcada por
    padrao). Sempre exclui eh_gestao (coordenacao/gestao) e eh_tipo_nao_clinico (bonus/premiacao/
    adiantamento - ver TIPOS_NAO_CONTAM_VOLUME) independente da tela de Operacoes, porque esses
    dois nao sao sobre ESCOPO de hospital/especialidade e sim sobre o que conta como plantao de
    verdade. Nao mexe no Excel, so reprocessa o dataframe ja carregado."""
    df = df.copy()
    operacoes_excluidas = set(operacoes_excluidas or [])
    df["chave_excluida"] = df["chave_operacao"].isin(operacoes_excluidas)
    df["conta_pro_nivel"] = (
        (~df["chave_excluida"]) & (~df["eh_gestao"]) & (~df["eh_tipo_nao_clinico"])
    )
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


def calcular_niveis(agg, niveis=None, medicos_gestores=None, custo_seguro_mes=None):
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
    certo na base.

    'custo_seguro_mes' permite recalcular com o custo do pacote de seguro customizado (editado na
    tela de Regras do Programa) em vez do CUSTO_SEGURO_TOTAL_MES padrao aprovado."""
    niveis = sorted(niveis or NIVEIS, key=lambda n: n["idx"])
    nivel_por_idx = niveis_para_dict(niveis)
    medicos_gestores = set(medicos_gestores or [])
    custo_seguro_mes = CUSTO_SEGURO_TOTAL_MES if custo_seguro_mes is None else custo_seguro_mes
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
            custo_seguro = custo_seguro_mes if info_vestido["tem_seguro"] else 0.0
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


def montar_base_completa(arquivo=None, niveis=None, medicos_gestores=None, custo_seguro_mes=None):
    """Pipeline completo: le, agrega, calcula niveis. Cacheable pela camada de UI."""
    agg = montar_agregado(arquivo)
    return calcular_niveis(
        agg, niveis=niveis, medicos_gestores=medicos_gestores, custo_seguro_mes=custo_seguro_mes
    )


def status_atual(niveis_df, anomes_referencia=None):
    """Snapshot do mes mais recente disponivel (ou anomes_referencia se passado) por medico."""
    if niveis_df.empty:
        return niveis_df
    am = anomes_referencia or niveis_df["anomes"].max()
    return niveis_df[niveis_df["anomes"] == am].copy()


def proximo_nivel_info(row):
    """Dado um snapshot-row de status_atual, calcula quanto falta pro proximo nivel (por
    volume - carencia adicional continua sendo tempo, nao da pra "comprar"). Usa n_fds_ou_noturno
    (a uniao, mesmo campo que _nivel_bruto usa de verdade) - corrigido em 2026-08-20, a versao
    anterior comparava com n_fds puro e ficava incoerente com a regra vigente. Sem uso em nenhuma
    tela ate essa correcao (funcao morta), entao nao ha call-site desatualizado pra ajustar."""
    nivel_atual = row["nivel_bruto"]
    if nivel_atual >= 4:
        return None
    prox = NIVEL_POR_IDX[nivel_atual + 1]
    faltam_plantoes = max(0, prox["min_plantoes"] - row["n_plantoes"])
    faltam_fds_ou_noturno = max(0, prox["min_fds"] - row["n_fds_ou_noturno"])
    return {
        "proximo_nivel": prox["nome"], "faltam_plantoes": faltam_plantoes,
        "faltam_fds_ou_noturno": faltam_fds_ou_noturno,
    }


# Beneficios por nivel (Programa_Constelacao_CallMed_v2.md secao 2) - cada nivel soma aos
# anteriores (Nivel 3 tem tudo do 1+2+3). Usado no "Relatorio do Medico" (tela + PDF pra entregar
# ao medico) - texto em tom de comunicado, nao o tom tecnico do documento de regras.
BENEFICIOS_NIVEL = {
    1: [
        "Suporte administrativo prioritário",
        "Apoio jurídico integral (retroatividade de 3 anos para fatos desconhecidos)",
        "Convênio médico básico",
        "Antecipação de valores de plantão (pago até 2 dias após o plantão)",
    ],
    2: [
        "Desconto em planos de saúde",
        "Antecipação dos plantões agendados",
        "Acesso ao programa de mindfulness",
    ],
    3: [
        "50% de reembolso em cursos (ACLS/PALS/COPA/SAVA, 1x/ano, até 3 localidades indicadas)",
        "Escala preferencial em unidades",
        "Seguro de Vida — R$ 99.000 (morte natural) / R$ 198.000 (morte acidental)",
        "DIT — R$ 166,66/dia em caso de incapacidade temporária",
        "Assistência Funeral Familiar — R$ 10.000",
        "RCP — Responsabilidade Civil Profissional, R$ 100.000, franquia zero",
    ],
    4: [
        "100% de reembolso em cursos",
        "15 dias de licença maternidade remunerada",
        "7 dias de licença paternidade remunerada",
        "Reconhecimento oficial em eventos CallMed",
    ],
}


def beneficios_acumulados(nivel):
    """Lista cumulativa de beneficios do Nivel 1 ate o nivel informado (cada nivel inclui tudo
    dos anteriores + os proprios)."""
    beneficios = []
    for n in range(1, int(nivel) + 1):
        beneficios.extend(BENEFICIOS_NIVEL.get(n, []))
    return beneficios


def tempo_no_nivel_atual(row, niveis=None):
    """Quantos meses o BENEFICIO do nivel vigente esta realmente ativo (streak do nivel menos a
    carencia que ja foi cumprida pra ele valer) - diferente do streak bruto, que conta tambem os
    meses "gastos" na propria carencia. Nivel 1 nao tem streak/carencia (e o piso), retorna None."""
    niveis = niveis or NIVEIS
    nivel_vestido = int(row["nivel_vestido"])
    if nivel_vestido < 2:
        return None
    carencia = niveis_para_dict(niveis)[nivel_vestido]["carencia_meses"]
    streak = int(row.get(f"streak_n{nivel_vestido}", 0))
    return max(1, streak - carencia)
