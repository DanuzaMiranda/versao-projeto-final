"""Caminhos do protótipo e leitura do .env. Nenhum segredo fica no código."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "data"
PASTA_SESSAO = RAIZ / ".sessao"
ARQUIVO_SESSAO = PASTA_SESSAO / "conversa.json"


def carregar_env() -> None:
    caminho = RAIZ / ".env"
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))
