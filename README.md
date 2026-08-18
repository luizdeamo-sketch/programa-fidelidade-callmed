# Programa Fidelidade CallMed — Constelação

Sistema interno (time administrativo apenas — médicos não têm acesso) para gestão do Programa
Constelação: níveis por médico, carência, custos de seguro e aumento de plantão, e bônus de
hospital em ramp-up.

## Rodando local

```bash
pip install -r requirements.txt
streamlit run app.py
```

Por padrão lê a base de plantões do caminho local do OneDrive (`config_caminhos.py`). Se não
encontrar, use o botão de upload dentro do próprio sistema (aba "📁 Fonte de dados").

## Publicado (Streamlit Community Cloud)

A nuvem não enxerga o OneDrive local — os dados são alimentados via upload manual pela tela
"📁 Fonte de dados" (exclusivo do papel master). O arquivo enviado fica salvo em `dados_upload/`
dentro do próprio deploy e some se o app reiniciar/redeployar — reenviar quando isso acontecer.

## ⚠️ Repositório deve ficar PRIVADO

`usuarios.py` contém senhas em texto puro (login simples, sem hash — ver aviso no topo do
arquivo). **Nunca torne este repositório público.**
