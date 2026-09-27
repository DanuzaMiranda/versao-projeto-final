"""Conversa com a Vera. Protótipo do desafio, com dados fictícios."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

RAIZ_SRC = Path(__file__).resolve().parent
if str(RAIZ_SRC) not in sys.path:
    sys.path.insert(0, str(RAIZ_SRC))

from agente import responder, tem_modelo
from conhecimento import abertura, carregar
from sessao import carregar as carregar_sessao
from sessao import limpar as limpar_sessao
from sessao import salvar as salvar_sessao

BASE = carregar()

st.set_page_config(
    page_title="Vera — alerta do cartão",
    page_icon="💳",
    layout="centered",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.4rem; max-width: 760px;}
    div[data-testid="stChatMessage"] p {font-size: 1.02rem; line-height: 1.45;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _gravar() -> None:
    salvar_sessao(st.session_state.mensagens, st.session_state.memoria)


def _iniciar() -> None:
    if "mensagens" not in st.session_state or "memoria" not in st.session_state:
        guardada = carregar_sessao()
        if guardada:
            st.session_state.mensagens = guardada["mensagens"]
            st.session_state.memoria = guardada["memoria"]
        else:
            st.session_state.mensagens = [
                {"role": "assistant", "content": abertura(BASE)}
            ]
            st.session_state.memoria = {"etapa": "aguardando_reconhecimento"}
            _gravar()
    if "usar_llm" not in st.session_state:
        st.session_state.usar_llm = tem_modelo()


def _enviar(texto: str) -> None:
    texto = texto.strip()
    if not texto:
        return
    st.session_state.mensagens.append({"role": "user", "content": texto})
    resultado = responder(
        texto,
        historico=st.session_state.mensagens,
        memoria=st.session_state.memoria,
        usar_llm=st.session_state.usar_llm,
        base=BASE,
    )
    st.session_state.mensagens.append(
        {"role": "assistant", "content": resultado["texto"]}
    )
    _gravar()


def _decisao_legivel() -> str:
    mapa = {
        "contestar": "Você quer contestar a compra.",
        "reconhecida": "Você reconheceu a compra nesta conversa.",
        "bloquear": "Você quer o bloqueio temporário.",
    }
    return mapa.get(st.session_state.memoria.get("decisao"), "Ainda sem uma decisão sua.")


_iniciar()

with st.sidebar:
    st.header("Esta sessão")
    st.write(f"**{BASE.perfil['nome']}**")
    st.write(f"Cartão final {BASE.perfil['cartao']['final']}")
    st.write("1 compra em alerta")
    st.write(_decisao_legivel())
    st.divider()
    if tem_modelo():
        st.session_state.usar_llm = st.toggle(
            "Usar modelo generativo",
            value=st.session_state.usar_llm,
            help="A resposta do modelo só entra se os valores em reais existirem na ficha.",
        )
    else:
        st.info(
            "Modo base de conhecimento. Para uma resposta generativa, "
            "crie um arquivo .env com OPENAI_API_KEY. O modelo também aceita "
            "um endpoint compatível, como o Ollama em OPENAI_BASE_URL."
        )
    st.caption(
        "Banco Aurora é fictício. Os dados são do protótipo. "
        "A Vera não bloqueia cartão, não pede senha e não promete estorno."
    )
    if st.button("Recomeçar conversa"):
        limpar_sessao()
        del st.session_state.mensagens
        del st.session_state.memoria
        st.rerun()
    st.caption("A conversa fica neste computador até você recomeçar.")

st.title("Vera")
st.write(
    "Assistente do alerta no cartão. Ela responde com a base desta sessão "
    "e diz quando a informação não está lá."
)

atalhos = [
    "Qual compra está em alerta?",
    "Não reconheço essa compra.",
    "Quanto gastei com alimentação?",
    "O que eu faço agora?",
]
for esquerda, direita in zip(atalhos[0::2], atalhos[1::2]):
    coluna_esquerda, coluna_direita = st.columns(2)
    if coluna_esquerda.button(esquerda, use_container_width=True):
        _enviar(esquerda)
        st.rerun()
    if coluna_direita.button(direita, use_container_width=True):
        _enviar(direita)
        st.rerun()

for mensagem in st.session_state.mensagens:
    with st.chat_message(mensagem["role"]):
        st.markdown(mensagem["content"].replace("$", r"\$"))

pergunta = st.chat_input("Escreva sua dúvida")
if pergunta:
    _enviar(pergunta)
    st.rerun()
