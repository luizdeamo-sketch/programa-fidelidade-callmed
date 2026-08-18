"""Cadastro de usuários do time administrativo do Programa Fidelidade.

Só o time adm acessa este sistema (médico não tem acesso - decisão do usuário, sessão
2026-08-18). 3 papéis: master (exclusivo pra ações sensíveis, ex.: disparar bônus de hospital em
ramp-up), gestor e analista (veem tudo, não disparam ações sensíveis).

Antes de usar de verdade: troque as senhas abaixo por algo só seu. Isso é uma barreira simples de
uso interno, não é um sistema de autenticação robusto (sem hash, sem recuperação de senha, sem
verificação de identidade) - serve pra saber quem é quem entre um grupo pequeno e confiável, não
pra proteger contra alguém mal intencionado.
"""

USUARIOS = {
    "luiz.amo@callmedsaude.com.br": {
        "nome": "Luiz Amo",
        "papel": "master",
        "senha": "constelacao2026",  # TROCAR - senha temporaria
    },
    # Pendente: dados do outro gestor - Luiz vai mandar depois.
    # "email-do-gestor@callmedsaude.com.br": {"nome": "...", "papel": "gestor", "senha": "..."},
    # Pendente: dados do analista - Luiz vai mandar depois.
    # "email-do-analista@callmedsaude.com.br": {"nome": "...", "papel": "analista", "senha": "..."},
}

PAPEIS_COM_ACAO_SENSIVEL = {"master"}  # so master dispara o bonus de ramp-up


def autenticar(email, senha):
    """Retorna o dict do usuario se email+senha baterem, senao None."""
    email = (email or "").strip().lower()
    user = USUARIOS.get(email)
    if user and user["senha"] == senha:
        return {"email": email, **user}
    return None
