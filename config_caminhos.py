"""Caminhos de dados do Programa Fidelidade CallMed (Constelação) - sistema separado do DRE.

DESDE 2026-08-20: a fonte PRINCIPAL de dados (plantoes + Apoio) e o Supabase (ver
supabase_client.py e core.consultar_plantoes_supabase()/consultar_apoio_supabase()), nao mais o
Excel local/OneDrive - o sistema deixou de depender de acesso a maquina pra funcionar. Os caminhos
abaixo (BASE_PLANTOES, UPLOAD_PLANTOES, APOIO_CUSTOMIZADO) continuam existindo so como caminho de
FALLBACK/OFFLINE (scripts, migracao, o botao "Reimportar da planilha local" da tela Apoio) - nao
sao mais lidos automaticamente pelo app.py."""
import os

# Pasta-base do projeto migrada do Desktop para o OneDrive em 2026-08-19 (sessao do usuario).
# Nao usada por nenhum outro caminho deste arquivo (BASE_PLANTOES usa BASE_ONEDRIVE_ANALISES,
# pasta separada) - mantida so por consistencia/compatibilidade.
BASE_DESKTOP = (
    r"C:\Users\LuizAmo\OneDrive - CALLMED SERVICOS MEDICOS E ANESTESIOLOGIA LTDA"
    r"\Operação e Estratégia - Operações e Estratégia\Financeiro CallMed"
)

# Fonte de dados do Programa Fidelidade (indicada pelo usuario, sessao 2026-08-18) - pasta
# separada "1.ANALISES LUIZ", MESMO PADRAO de aba "BD" da base antiga, porem com uma coluna a
# mais no inicio (tudo desloca +1) e uma coluna nova no fim, "Especialidade", que classifica
# cada linha em Anestesia/Enfermaria/UTI/Adm/CallMed/Ambulatorio/Oftalto/etc - usada como fonte
# de verdade pro escopo "vale para todas as operacoes de anestesia" do programa (ver core.py).
# So existe/e acessivel rodando LOCAL (na maquina do Luiz, com OneDrive sincronizado) - no
# Streamlit Community Cloud esse caminho nao existe, por isso o app usa UPLOAD_PLANTOES como
# fonte quando publicado (ver resolver_base_plantoes abaixo).
BASE_ONEDRIVE_ANALISES = (
    r"C:\Users\LuizAmo\OneDrive - CALLMED SERVICOS MEDICOS E ANESTESIOLOGIA LTDA"
    r"\Financeiro - Documentos\1.ANALISES LUIZ"
)
BASE_PLANTOES = os.path.join(
    BASE_ONEDRIVE_ANALISES, "BD Pantões 2021_Mai 26_ Novos Estudos Financeiros.xlsx"
)

# Onde o Excel enviado pelo botao de upload (tela de Configuracoes, master) fica salvo dentro do
# proprio deploy - sobrevive entre reruns/usuarios enquanto o app estiver no ar (some se o app
# reiniciar/redeployar no Streamlit Cloud - precisa reenviar depois de um redeploy).
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados_upload")
UPLOAD_PLANTOES = os.path.join(UPLOAD_DIR, "plantoes.xlsx")

# Mapeamento Local -> Setor Definido/Especialidade GERENCIADO PELO SISTEMA (tela "🗂️ Apoio",
# sessao 2026-08-20) - substitui a dependencia de consultar a aba "Apoio" do Excel toda vez.
# Nasce importado de la (bootstrap, uma vez), dai em diante o master edita e o sistema persiste
# aqui, direto. MESMA ressalva do UPLOAD_PLANTOES acima: sobrevive a reruns/reinicios locais, mas
# some se o app redeployar no Streamlit Community Cloud (filesystem efemero por la).
APOIO_CUSTOMIZADO = os.path.join(UPLOAD_DIR, "apoio_customizado.json")


def resolver_base_plantoes():
    """Prioridade: upload feito pela tela de Configuracoes > caminho local do OneDrive.
    E o upload que faz o sistema funcionar quando publicado na nuvem (o OneDrive local so existe
    na maquina do Luiz)."""
    if os.path.exists(UPLOAD_PLANTOES):
        return UPLOAD_PLANTOES
    return BASE_PLANTOES
