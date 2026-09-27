"""Vera: respostas presas à base, com modelo generativo opcional."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from config import carregar_env as _carregar_env
from conhecimento import (
    ALIASES_CATEGORIA,
    BUSCA_DESCRICAO,
    Base,
    brl,
    carregar,
    normalizar,
    tem_termo,
)
from prompts import SYSTEM_PROMPT


def tem_modelo() -> bool:
    _carregar_env()
    return bool(os.environ.get("OPENAI_API_KEY"))


def _fontes(*nomes: str) -> str:
    return "Fonte: " + ", ".join(nomes) + "."


def _resposta(texto: str, fontes: list[str], intent: str) -> dict:
    return {
        "texto": texto.rstrip() + "\n\n" + _fontes(*fontes),
        "fontes": fontes,
        "modo": "base",
        "intent": intent,
    }


def _categoria_pedida(texto: str) -> str | None:
    for categoria, aliases in ALIASES_CATEGORIA.items():
        if any(tem_termo(texto, alias) for alias in aliases):
            return categoria
    return None


def _lancamentos_por_descricao(base: Base, texto: str) -> list[dict]:
    achados = []
    for termo, descricao in BUSCA_DESCRICAO:
        if tem_termo(texto, termo):
            achados.extend(
                t for t in base.transacoes if t["descricao"] == descricao
            )
    vistos = set()
    unicos = []
    for item in achados:
        chave = (item["data"], item["descricao"])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(item)
    return unicos


def _pede_total(texto: str) -> bool:
    return any(termo in texto for termo in ("gastei", "gastos", "paguei", "quanto saiu", "no mes"))


def _ultima_fala_assistente(historico: list[dict] | None) -> str:
    if not historico:
        return ""
    for item in reversed(historico):
        if item.get("role") == "assistant":
            return normalizar(item.get("content", ""))
    return ""


def _perguntou_se_reconhece(historico: list[dict] | None) -> bool:
    return "reconhece essa compra" in _ultima_fala_assistente(historico)


def _alerta_aberto(base: Base, memoria: dict) -> str:
    if not base.alerta_em_aberto(memoria):
        return ""
    return (
        f"O alerta segue em aberto: {base.resumo_alerta()}. "
        "Decida essa compra antes de tratar o valor como dinheiro livre."
    )


def _texto_contestacao(base: Base) -> str:
    regras = base.regras["contestacao"]
    return (
        f"Registrei nesta conversa que você não reconhece a compra. "
        f"O próximo passo é contestar em até {regras['prazo_cliente_dias_corridos']} "
        f"dias corridos. {regras['contagem']} "
        f"A análise leva até {regras['analise_dias_uteis']} dias úteis. "
        "O estorno não é garantido. "
        "Se quiser, o bloqueio temporário no App Aurora é imediato, reversível e "
        "não cancela a fatura. Eu não bloqueio o cartão daqui. "
        f"O canal oficial é {base.regras['canal_oficial']}."
    )


def _texto_reconhecida(base: Base) -> str:
    return (
        "Registrei nesta conversa que você reconhece a compra "
        f"{base.resumo_alerta()}. A compra continua na fatura. "
        f"{base.regras['contestacao']['contagem']} "
        "Se mudar de ideia dentro desse prazo, ainda dá para contestar. "
        "O estorno não é garantido."
    )


def _texto_bloqueio(base: Base) -> str:
    return (
        "Registrei nesta conversa que você quer o bloqueio temporário. "
        "No Banco Aurora ele é imediato e reversível pelo App Aurora. "
        "Não cancela a fatura e não apaga a compra que já entrou. "
        "Eu não executo o bloqueio daqui. "
        f"O canal oficial é {base.regras['canal_oficial']}. "
        "A contestação é um passo separado: o estorno não é garantido."
    )


def _produtos_baixos(base: Base) -> str:
    linhas = []
    for produto in base.produtos_risco("baixo"):
        linhas.append(
            f"{produto['nome']}: {produto['rentabilidade']}, "
            f"aporte mínimo {brl(produto['aporte_minimo'])}. "
            f"{produto['indicado_para']}"
        )
    return " ".join(linhas)


def _resposta_base(mensagem: str, memoria: dict, base: Base, historico: list[dict] | None = None) -> dict:
    texto = normalizar(mensagem)

    if any(termo in texto for termo in ("ignore as regras", "ignore as instrucoes", "finja que")):
        return _resposta(
            "Não confirmo estorno. A análise leva até "
            f"{base.regras['contestacao']['analise_dias_uteis']} dias úteis "
            "e o estorno não é garantido.",
            ["regras_banco.json"],
            "recusa",
        )

    pedido_secreto = any(
        termo in texto
        for termo in (
            "qual a senha",
            "qual e a senha",
            "me passa a senha",
            "me passa o cvv",
            "meu cvv",
            "numero completo",
            "cartao completo",
            "cpf de outro",
            "cpf do cliente",
            "dados de outro",
            "outro cliente",
            "senha do cliente",
        )
    )
    if pedido_secreto or (
        tem_termo(texto, "senha") and any(p in texto for p in ("passa", "qual", "me da", "informe"))
    ):
        return _resposta(
            "Não tenho senha, CVV, token nem dados de outra pessoa. "
            "Também não peço esses dados. Posso seguir com o alerta do cartão "
            f"final {base.perfil['cartao']['final']}.",
            ["regras_banco.json"],
            "recusa",
        )

    if any(termo in texto for termo in ("golpe agora", "estao no telefone", "pediram o codigo", "codigo sms", "alguem ligou")):
        return _resposta(
            "Se alguém está pedindo código, senha ou CVV agora, não passe esses dados. "
            "O próximo passo é bloquear o cartão no App Aurora e ligar para "
            f"{base.regras['canal_oficial']}. Eu não peço esses dados e não bloqueio o cartão daqui.",
            ["faq_seguranca.json", "regras_banco.json"],
            "golpe",
        )

    perguntou = _perguntou_se_reconhece(historico) and memoria.get("decisao") is None
    if texto in {"sim", "s"} and perguntou:
        memoria["decisao"] = "reconhecida"
        memoria["etapa"] = "decidido"
        return _resposta(_texto_reconhecida(base), ["transacoes.csv", "regras_banco.json"], "reconhecer")

    if texto in {"nao", "n"} and perguntou:
        memoria["decisao"] = "contestar"
        memoria["etapa"] = "decidido"
        return _resposta(_texto_contestacao(base), ["regras_banco.json", "transacoes.csv"], "contestar")

    if texto in {"sim", "s", "nao", "n"} and memoria.get("decisao") is None:
        return _resposta(
            f"Para eu registrar uma decisão, responda sobre a compra em alerta: {base.resumo_alerta()}. "
            "Diga se você reconhece essa compra.",
            ["transacoes.csv"],
            "proximo_passo",
        )

    if any(termo in texto for termo in ("nao reconheco", "nao fui eu", "nao foi eu", "contestar", "desconheco")):
        memoria["decisao"] = "contestar"
        memoria["etapa"] = "decidido"
        return _resposta(_texto_contestacao(base), ["regras_banco.json", "transacoes.csv"], "contestar")

    if any(termo in texto for termo in ("pode liberar", "reconheco a compra", "eu reconheco", "fui eu sim")) or (
        tem_termo(texto, "fui eu") and "nao" not in texto
    ):
        memoria["decisao"] = "reconhecida"
        memoria["etapa"] = "decidido"
        return _resposta(_texto_reconhecida(base), ["transacoes.csv", "regras_banco.json"], "reconhecer")

    explica_bloqueio = any(termo in texto for termo in ("como funciona", "o que e o bloqueio", "o que faz o bloqueio"))
    quer_bloquear = any(
        termo in texto
        for termo in ("quero bloquear", "pode bloquear", "bloquear o", "bloqueia o", "fazer o bloqueio")
    )
    if quer_bloquear and not explica_bloqueio:
        memoria["decisao"] = "bloquear"
        memoria["etapa"] = "decidido"
        return _resposta(_texto_bloqueio(base), ["produtos_financeiros.json", "regras_banco.json"], "bloquear")

    if any(termo in texto for termo in ("estorno", "reembolso", "dinheiro de volta", "dinheiro ja", "ja voltou")):
        return _resposta(
            "Contestar abre a análise. No Banco Aurora, essa análise leva até "
            f"{base.regras['contestacao']['analise_dias_uteis']} dias úteis. "
            "O estorno não é garantido. Não tenho, nesta base, um estorno aprovado para a Marina.",
            ["regras_banco.json"],
            "estorno",
        )

    fora = ("previsao do tempo", "temperatura", "clima", "futebol", "receita de bolo", "horoscopo", "piada")
    financeiro = (
        "gasto", "gastei", "cartao", "alerta", "compra", "estorno", "invest",
        "reserva", "renda", "marina", "transac", "bloque", "contest", "produto",
        "cdb", "selic", "tesouro", "fatura", "fraude", "saldo",
    )
    if any(termo in texto for termo in fora) and not any(termo in texto for termo in financeiro):
        return _resposta(
            "Eu cuido do cartão e do orçamento da Marina nesta sessão. "
            "Não tenho informação sobre esse assunto.",
            ["regras_banco.json"],
            "fora_de_escopo",
        )

    if any(termo in texto for termo in ("bitcoin", "fundo xyz", "xyz", "petrobras", "cripto")):
        return _resposta(
            "Não tenho essa informação na base do Banco Aurora.",
            ["produtos_financeiros.json"],
            "sem_informacao",
        )

    if "selic hoje" in texto or "taxa selic" in texto or "cotacao" in texto:
        return _resposta(
            "Não tenho a taxa Selic do dia nem um valor em reais. "
            "No catálogo, o Tesouro Selic rende 100% da Selic.",
            ["produtos_financeiros.json"],
            "sem_informacao",
        )

    if any(termo in texto for termo in ("pesa", "por cento", "percent", "representa da renda", "na minha renda")):
        return _resposta(
            f"A compra em alerta é {base.resumo_alerta()}. "
            f"Ela equivale a {base.peso_na_renda()} da renda mensal de {brl(base.perfil['renda_mensal'])}.",
            ["transacoes.csv", "perfil_cliente.json"],
            "simulacao",
        )

    if any(termo in texto for termo in ("sem o alerta", "sem essa compra", "tirar essa compra", "desconsiderar", "se eu contestar o valor")):
        return _resposta(
            f"As saídas de outubro de 2025 somam {brl(base.total_saidas)}. "
            f"Sem a compra em alerta, ficam {brl(base.saidas_sem_alerta)}. "
            "Essa conta é demonstrativa: contestar não apaga o lançamento da fatura "
            "enquanto a análise não termina, e o estorno não é garantido.",
            ["transacoes.csv", "regras_banco.json"],
            "simulacao",
        )

    if "analise" in texto and any(termo in texto for termo in ("quanto", "prazo", "demora")):
        return _resposta(
            "A análise da contestação leva até "
            f"{base.regras['contestacao']['analise_dias_uteis']} dias úteis. "
            "O estorno não é garantido. Não tenho, nesta base, um estorno aprovado para a Marina.",
            ["regras_banco.json"],
            "estorno",
        )

    if _pede_total(texto) or "quanto foi" in texto or "quanto entrou" in texto or "meu salario" in texto:
        descricao = _lancamentos_por_descricao(base, texto)
        if descricao and not _categoria_pedida(texto):
            total = sum(item["valor"] for item in descricao)
            nomes = ", ".join(item["descricao"] for item in descricao)
            return _resposta(
                f"Em outubro de 2025, {nomes} soma {brl(total)}.",
                ["transacoes.csv"],
                "gastos",
            )
        categoria = _categoria_pedida(texto)
        if categoria:
            total = base.soma_categoria(categoria)
            rotulo = {
                "alimentacao": "alimentação",
                "moradia": "moradia",
                "transporte": "transporte",
                "saude": "saúde",
                "lazer": "lazer",
                "compras": "compras",
                "receita": "receita",
            }[categoria]
            frase = f"Em outubro de 2025, {rotulo} soma {brl(total)}."
            em_alerta = [t for t in base.por_categoria(categoria) if t["status"] == "alerta"]
            if em_alerta:
                frase += (
                    f" Desse valor, {brl(sum(t['valor'] for t in em_alerta))} "
                    "ainda estão em alerta."
                )
            return _resposta(frase, ["transacoes.csv"], "gastos")
        if any(termo in texto for termo in ("quanto entrou", "meu salario", "entradas")):
            return _resposta(
                f"Em outubro de 2025, as entradas somam {brl(base.total_entradas)}.",
                ["transacoes.csv"],
                "gastos",
            )
        if _pede_total(texto):
            return _resposta(
                f"Em outubro de 2025, as saídas somam {brl(base.total_saidas)}. "
                f"Desse total, {brl(base.alerta['valor'])} ainda estão em alerta.",
                ["transacoes.csv"],
                "gastos",
            )

    if any(termo in texto for termo in ("por que alert", "porque alert", "o que e um alerta", "o que significa", "compra suspeita", "qual compra", "compra em alerta", "me explica o alerta", "ver o alerta")):
        memoria["etapa"] = memoria.get("etapa") or "aguardando_reconhecimento"
        return _resposta(
            f"A compra em alerta é {base.resumo_alerta()}. {base.motivos_alerta()} "
            "Você reconhece essa compra?",
            ["transacoes.csv", "regras_banco.json"],
            "alerta",
        )

    if any(termo in texto for termo in ("o que faco", "proximo passo", "e agora", "como resolver", "o que eu faco")):
        memoria["etapa"] = memoria.get("etapa") or "aguardando_reconhecimento"
        if memoria.get("decisao") == "contestar":
            return _resposta(_texto_contestacao(base), ["regras_banco.json"], "proximo_passo")
        if memoria.get("decisao") == "reconhecida":
            return _resposta(_texto_reconhecida(base), ["transacoes.csv", "regras_banco.json"], "proximo_passo")
        return _resposta(
            f"A compra em aberto é {base.resumo_alerta()}. "
            "O próximo passo é dizer se você reconhece essa compra. "
            f"{base.regras['contestacao']['contagem']} O estorno não é garantido.",
            ["transacoes.csv", "regras_banco.json"],
            "proximo_passo",
        )

    if any(termo in texto for termo in ("investir", "investimento", "recomenda", "tesouro", "cdb", "lci", "fundo de acoes", "fundo multimercado", "onde coloco")):
        aviso = _alerta_aberto(base, memoria)
        if "fundo de acoes" in texto:
            corpo = (
                "O Fundo de Ações está no catálogo com risco alto e rentabilidade variável. "
                "O perfil desta sessão é conservador, então ele fica de fora da leitura "
                "de produtos para a Marina. "
                f"Produtos de risco baixo: {_produtos_baixos(base)} "
                "Isso é leitura do catálogo, não recomendação de investimento."
            )
        elif "fundo multimercado" in texto:
            corpo = (
                "O Fundo Multimercado está no catálogo com risco medio e rentabilidade CDI + 2%. "
                "O perfil desta sessão é conservador, então ele fica de fora da leitura "
                "de produtos para a Marina. "
                f"Produtos de risco baixo: {_produtos_baixos(base)} "
                "Isso é leitura do catálogo, não recomendação de investimento."
            )
        else:
            corpo = (
                "O perfil desta sessão é conservador. No catálogo, os produtos de risco baixo são estes. "
                f"{_produtos_baixos(base)} "
                "Isso é leitura do catálogo, não recomendação de investimento."
            )
        prefixo = f"{aviso}\n\n" if aviso else ""
        return _resposta(prefixo + corpo, ["perfil_cliente.json", "produtos_financeiros.json", "transacoes.csv"], "investimento")

    produto = base.produto_por_nome(texto)
    if produto and produto["categoria"] == "seguranca_cartao":
        return _resposta(
            f"{produto['nome']}: {produto['o_que_faz']} {produto['efeito']} {produto['limite']}",
            ["produtos_financeiros.json"],
            "produto",
        )
    if any(termo in texto for termo in ("cartao virtual", "aviso de compra", "contestacao de compra")):
        return _resposta(
            "Não tenho essa informação na base do Banco Aurora.",
            ["produtos_financeiros.json"],
            "sem_informacao",
        )

    if any(termo in texto for termo in ("meu nome", "quem sou", "meu perfil", "qual e o meu perfil", "renda")):
        return _resposta(
            f"Nesta sessão, você é {base.perfil['nome']}, {base.perfil['profissao']}. "
            f"A renda mensal registrada é {brl(base.perfil['renda_mensal'])}. "
            f"O perfil de investidor é {base.perfil['perfil_investidor']}. "
            f"O cartão é o final {base.perfil['cartao']['final']}. "
            f"O objetivo registrado é: {base.perfil['objetivo_principal']}.",
            ["perfil_cliente.json"],
            "perfil",
        )

    if any(termo in texto for termo in ("atendimento", "historico", "da ultima vez", "conversa anterior", "ja falei")):
        linhas = []
        for item in base.historico:
            estado = "resolvido" if item["resolvido"] == "sim" else "em aberto"
            linhas.append(
                f"{item['data']}, por {item['canal']}, tema {item['tema']}: {item['resumo']} ({estado})."
            )
        return _resposta(" ".join(linhas), ["historico_atendimento.csv"], "historico")

    if "reserva" in texto:
        aviso = _alerta_aberto(base, memoria)
        corpo = (
            f"A reserva atual é {brl(base.perfil['reserva_emergencia_atual'])}. "
            f"A meta é {brl(base.perfil['reserva_emergencia_meta'])}. "
            f"Faltam {brl(base.falta_reserva)}."
        )
        prefixo = f"{aviso}\n\n" if aviso else ""
        return _resposta(prefixo + corpo, ["perfil_cliente.json", "transacoes.csv"], "reserva")

    if any(termo in texto for termo in ("como o modelo", "xgboost", "inteligencia artificial detecta", "notebook")):
        estudo = next(item for item in base.faq if item["id"] == "modelo")
        return _resposta(estudo["resposta"], ["faq_seguranca.json", "regras_banco.json"], "modelo")

    if "alerta" in texto or "fraude" in texto:
        memoria["etapa"] = memoria.get("etapa") or "aguardando_reconhecimento"
        return _resposta(
            f"A compra em alerta é {base.resumo_alerta()}. {base.motivos_alerta()} "
            "Você reconhece essa compra?",
            ["transacoes.csv", "regras_banco.json"],
            "alerta",
        )

    return _resposta(
        "Não tenho essa informação na base do Banco Aurora. "
        "Posso falar do alerta, dos gastos de outubro, do catálogo e do próximo passo.",
        ["regras_banco.json"],
        "sem_informacao",
    )


def _valores_citados(texto: str) -> set[int]:
    achados = set()
    for bruto in re.findall(r"R\$\s*[\d.]+,\d{2}", texto):
        numero = bruto.split("$", 1)[1].strip().replace(".", "").replace(",", ".")
        achados.add(int(round(float(numero) * 100)))
    return achados


def _llm_aceitavel(texto: str, base: Base, intent: str) -> bool:
    if intent in {"recusa", "fora_de_escopo", "sem_informacao"}:
        return False
    if not texto.strip():
        return False
    if re.search(r"senha\s*(é|e|:)\s*\S+", texto, flags=re.IGNORECASE):
        return False
    if re.search(r"estorno\s+(já|ja)\s+(foi\s+)?aprovado", normalizar(texto)):
        return False
    citados = _valores_citados(texto)
    return citados <= base.cents_conhecidos


def _chamar_modelo(mensagem: str, historico: list[dict], base: Base) -> str | None:
    _carregar_env()
    chave = os.environ.get("OPENAI_API_KEY")
    if not chave:
        return None
    url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    modelo = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    anteriores = list(historico[-8:])
    if (
        anteriores
        and anteriores[-1].get("role") == "user"
        and anteriores[-1].get("content") == mensagem
    ):
        anteriores = anteriores[:-1]
    mensagens = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\nCONTEXTO:\n" + base.contexto_completo()},
    ]
    for item in anteriores:
        if item.get("role") in {"user", "assistant"}:
            mensagens.append({"role": item["role"], "content": item["content"]})
    mensagens.append({"role": "user", "content": mensagem})
    corpo = json.dumps(
        {"model": modelo, "temperature": 0.2, "messages": mensagens},
        ensure_ascii=False,
    ).encode("utf-8")
    pedido = urllib.request.Request(
        url + "/chat/completions",
        data=corpo,
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            payload = json.loads(resposta.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError):
        return None


def responder(
    mensagem: str,
    historico: list[dict] | None = None,
    memoria: dict | None = None,
    usar_llm: bool = False,
    base: Base | None = None,
) -> dict:
    base = base or carregar()
    memoria = memoria if memoria is not None else {}
    resultado = _resposta_base(mensagem, memoria, base, historico)
    if not usar_llm:
        return resultado
    texto_modelo = _chamar_modelo(mensagem, historico or [], base)
    if texto_modelo and _llm_aceitavel(texto_modelo, base, resultado["intent"]):
        return {
            "texto": texto_modelo,
            "fontes": resultado["fontes"],
            "modo": "llm",
            "intent": resultado["intent"],
        }
    return resultado
