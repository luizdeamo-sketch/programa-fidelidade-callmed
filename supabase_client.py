"""Cliente Supabase do Programa Fidelidade CallMed (sessão 2026-08-20: base de plantões e Apoio
migradas do Excel local pro Supabase, pra não depender mais de acesso à máquina/OneDrive).

Credenciais em st.secrets["supabase"] (mesmo padrão de usuarios.py) - NÃO hardcoded aqui, mesmo a
chave "publishable"/anon sendo tecnicamente segura de expor no client-side, porque combinada com
as policies de RLS ("for all using (true)") ela dá acesso de escrita total às tabelas - tratada
com o mesmo cuidado das outras credenciais deste projeto.
"""
import streamlit as st
from supabase import create_client


@st.cache_resource
def get_client():
    """Cliente Supabase cacheado por processo (nao por sessao - a conexao pode ser reaproveitada
    entre usuarios, e criar um client novo por rerun seria desperdicio)."""
    cfg = st.secrets["supabase"]
    return create_client(cfg["url"], cfg["key"])
