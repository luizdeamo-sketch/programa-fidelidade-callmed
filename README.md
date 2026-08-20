# CallMed Premium

Sistema interno (time administrativo apenas — médicos não têm acesso) para gestão do programa de
fidelidade: níveis por médico, carência, custos de seguro e aumento de plantão, bônus de hospital
em ramp-up, e o comunicado individual (com PDF) entregável ao médico.

## Rodando local

```bash
pip install -r requirements.txt
streamlit run app.py
```

A base de plantões e o mapeamento "Apoio" (Local → Especialidade) vivem no **Supabase** (ver
`supabase_client.py`), não mais no Excel/OneDrive local — o sistema roda igual em qualquer máquina
que tenha as credenciais em `.streamlit/secrets.toml` (ver `secrets.toml.exemplo`). Pra atualizar
dados, envie uma planilha via aba "📁 Fonte de dados" (upsert por período, sem duplicar histórico).

## Publicado (Streamlit Community Cloud)

Configure as mesmas chaves de `.streamlit/secrets.toml` no painel Settings → Secrets do app na
nuvem. Como a base já mora no Supabase, o deploy na nuvem funciona igual ao local — não depende
de acesso a nenhum caminho de arquivo da máquina de ninguém.

## Repositório público — sem segredo no código

Este repositório é **público** intencionalmente. Todas as credenciais (login dos usuários,
Supabase) ficam em `st.secrets`/`.streamlit/secrets.toml` — **gitignored, nunca commitado**. Antes
de mudar isso, revise `usuarios.py` (login simples, sem hash — aviso no topo do arquivo).
