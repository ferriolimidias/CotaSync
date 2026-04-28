"""
Cérebro do CotaSync: agente LangChain com ChatOpenAI e tools operacionais.

Integração Streamlit: use `processar_mensagem` (assíncrona) ou `asyncio.run(...)` no app.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
# LangChain 1.x: AgentExecutor e create_tool_calling_agent estão em `langchain-classic`
# (o pacote de compatibilidade; o top-level `langchain` deixou de reexportá-los).
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from backend.motor_browser import acionar_ia_cartografa, consultar_erp_real

load_dotenv()
_ROOT = Path(__file__).resolve().parent.parent
_UI_MAP_PATH = _ROOT / "ui_map.json"
sessoes_usuarios = {"admin": {"estado": "NORMAL", "acao_pendente": None}}


def carregar_ui_map() -> dict:
    if not _UI_MAP_PATH.is_file():
        return {"acoes_conhecidas": {}}
    try:
        dados = json.loads(_UI_MAP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"acoes_conhecidas": {}}

    if not isinstance(dados, dict):
        return {"acoes_conhecidas": {}}
    acoes = dados.get("acoes_conhecidas")
    if not isinstance(acoes, dict):
        dados["acoes_conhecidas"] = {}
    return dados


def salvar_ui_map(dados: dict) -> None:
    payload = dados if isinstance(dados, dict) else {"acoes_conhecidas": {}}
    if not isinstance(payload.get("acoes_conhecidas"), dict):
        payload["acoes_conhecidas"] = {}
    _UI_MAP_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _gerar_nome_acao(ui_map: dict) -> str:
    acoes = ui_map.get("acoes_conhecidas", {})
    if not isinstance(acoes, dict):
        acoes = {}
    indice = 1
    while True:
        nome = f"acao_nova_{indice:02d}"
        if nome not in acoes:
            return nome
        indice += 1


@tool
async def consultar_cadastro_erp(documento: str) -> str:
    """
    Consulta o cadastro de um cliente no ERP a partir do CNPJ ou CPF.

    Args:
        documento: CNPJ ou CPF apenas com dígitos ou formatado.

    Returns:
        Resumo textual (navegação real + evidência em ficheiro) para o LLM.
    """
    resultado = await consultar_erp_real(documento)
    if resultado.get("status") != "sucesso":
        return (
            "Falha na automação web. Detalhes: "
            f"{resultado.get('texto_extraido', 'erro desconhecido')}"
        )
    texto = resultado.get("texto_extraido", "")
    caminho = resultado.get("caminho_imagem", "")
    return (
        f"A busca retornou: {texto}. Print da evidência salvo em: {caminho}"
    )


def _criar_llm() -> ChatOpenAI:
    # gpt-4o-mini: rápido e econômico; temperatura 0 para respostas estáveis em operação.
    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=os.getenv("OPENAI_API_KEY") or None,
    )


def _historico_dicts_para_mensagens(historico: list[Any]) -> list[BaseMessage]:
    """
    Converte o histórico vindo do Streamlit (`role` + `content`) em mensagens LangChain.
    Ignora entradas sem role reconhecida.
    """
    mensagens: list[BaseMessage] = []
    for item in historico or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content", "")
        if role == "user":
            mensagens.append(HumanMessage(content=str(content)))
        elif role == "assistant":
            mensagens.append(AIMessage(content=str(content)))
    return mensagens


def criar_agente_executor() -> AgentExecutor:
    """
    Monta o agente com tools e prompt compatível com `create_tool_calling_agent`.
    """
    llm = _criar_llm()
    tools = [consultar_cadastro_erp]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "Você é o CotaSync, assistente operacional. "
                "Use as ferramentas quando precisar de dados de sistemas externos. "
                "Seja objetivo e cite o documento consultado quando aplicável.",
            ),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
    )


async def processar_mensagem(mensagem_usuario: str, historico: list | None = None) -> str:
    """
    Ponto principal de entrada do chat: executa o agente e devolve só o texto final.

    Args:
        mensagem_usuario: Texto atual digitado (ou injetado pela UI).
        historico: Lista de dicts `{"role": "user"|"assistant", "content": "..."}` com
            mensagens anteriores (não incluir a mensagem atual).

    Returns:
        Resposta natural da IA (após tools, se houver).
    """
    historico = historico if historico is not None else []
    sessao = sessoes_usuarios.setdefault("admin", {"estado": "NORMAL", "acao_pendente": None})
    estado = str(sessao.get("estado", "NORMAL"))
    mensagem_normalizada = str(mensagem_usuario or "").lower()

    if estado == "ESPERANDO_ENSINO":
        sessao["estado"] = "APRENDENDO"
        nome_acao = str(sessao.get("acao_pendente") or "acao_nova_01")
        novos_passos = await acionar_ia_cartografa(nome_acao, mensagem_usuario)
        ui_map = carregar_ui_map()
        ui_map.setdefault("acoes_conhecidas", {})
        ui_map["acoes_conhecidas"][nome_acao] = novos_passos
        try:
            salvar_ui_map(ui_map)
        except OSError:
            sessao["estado"] = "NORMAL"
            sessao["acao_pendente"] = None
            return (
                "Entendi o passo a passo, mas nao consegui salvar no ui_map.json agora. "
                "Pode tentar novamente em instantes?"
            )

        sessao["estado"] = "NORMAL"
        sessao["acao_pendente"] = None
        return "Pronto, chefe! Aprendi o caminho e salvei na minha memória. A ação já está disponível!"

    if estado == "NORMAL" and ("ensinar" in mensagem_normalizada or "aprender" in mensagem_normalizada):
        ui_map = carregar_ui_map()
        sessao["estado"] = "ESPERANDO_ENSINO"
        sessao["acao_pendente"] = _gerar_nome_acao(ui_map)
        return "Ainda não aprendi essa tarefa. Pode me explicar o passo a passo de onde eu clico no sistema?"

    chat_history = _historico_dicts_para_mensagens(historico)
    executor = criar_agente_executor()
    resultado = await executor.ainvoke(
        {
            "input": mensagem_usuario,
            "chat_history": chat_history,
        }
    )
    return str(resultado.get("output", "")).strip()


def _normalizar_chat_history_para_executor(chat_history: list[Any] | None) -> list[Any]:
    """Aceita dicts estilo Streamlit ou mensagens LangChain já instanciadas."""
    raw = chat_history or []
    if not raw:
        return []
    if isinstance(raw[0], dict):
        return _historico_dicts_para_mensagens(raw)
    return raw


async def executar_agente(
    mensagem_usuario: str,
    chat_history: list[Any] | None = None,
) -> dict[str, Any]:
    """
    Variante que retorna o dict completo do AgentExecutor (útil para API / logs).
    """
    executor = criar_agente_executor()
    return await executor.ainvoke(
        {
            "input": mensagem_usuario,
            "chat_history": _normalizar_chat_history_para_executor(chat_history),
        }
    )
