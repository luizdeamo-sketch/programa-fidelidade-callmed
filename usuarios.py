"""Cadastro de usuários do time administrativo do CallMed Premium.

Só o time adm acessa este sistema (médico não tem acesso - decisão do usuário, sessão
2026-08-18). 3 papéis: master (exclusivo pra ações sensíveis, ex.: disparar bônus de hospital em
ramp-up), gestor e analista (veem tudo, não disparam ações sensíveis).

As credenciais NÃO ficam mais neste arquivo (que vai pro GitHub) - vêm do st.secrets do
Streamlit, configurado em .streamlit/secrets.toml (local, sempre no .gitignore) ou na tela de
"Secrets" do Streamlit Community Cloud quando publicado. Isso permite deixar o repositório
público sem expor nenhuma senha.

Aviso de segurança: mesmo fora do código, ainda é login simples (email + senha em texto, sem
hash, sem recuperação). Serve pra identificar quem é quem entre um grupo pequeno e confiável, não
é proteção contra acesso mal intencionado.
"""
import streamlit as st

PAPEIS_COM_ACAO_SENSIVEL = {"master"}  # so master dispara o bonus de ramp-up


def _carregar_usuarios():
    try:
        return {email.lower(): dict(dados) for email, dados in st.secrets["usuarios"].items()}
    except (KeyError, FileNotFoundError):
        st.error(
            "Nenhum usuário configurado em st.secrets['usuarios']. Crie "
            ".streamlit/secrets.toml localmente (veja secrets.toml.exemplo) ou configure os "
            "Secrets na tela do Streamlit Community Cloud."
        )
        return {}


def autenticar(email, senha):
    """Retorna o dict do usuario se email+senha baterem, senao None."""
    email = (email or "").strip().lower()
    usuarios = _carregar_usuarios()
    user = usuarios.get(email)
    if user and user["senha"] == senha:
        return {"email": email, **user}
    return None
