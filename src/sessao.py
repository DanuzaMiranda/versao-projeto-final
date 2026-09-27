"""Guarda a conversa neste computador para a Vera lembrar a decisão."""

from __future__ import annotations

import json
from pathlib import Path

from config import ARQUIVO_SESSAO, PASTA_SESSAO


def carregar(caminho: Path = ARQUIVO_SESSAO) -> dict | None:
    if not caminho.exists():
        return None
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    mensagens = dados.get("mensagens")
    memoria = dados.get("memoria")
    if not isinstance(mensagens, list) or not isinstance(memoria, dict):
        return None
    return {"mensagens": mensagens, "memoria": memoria}


def salvar(mensagens: list[dict], memoria: dict, caminho: Path = ARQUIVO_SESSAO) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(
            {"mensagens": mensagens, "memoria": memoria},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def limpar(caminho: Path = ARQUIVO_SESSAO) -> None:
    caminho.unlink(missing_ok=True)
    if caminho.parent == PASTA_SESSAO and caminho.parent.exists() and not any(caminho.parent.iterdir()):
        caminho.parent.rmdir()
