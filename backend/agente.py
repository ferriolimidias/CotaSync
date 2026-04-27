"""
Cérebro do CotaSync: agente LangChain com ChatOpenAI e tools operacionais.

Próximas iterações: conectar ao FastAPI/Streamlit e enriquecer o prompt com contexto omnichannel.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

load_dotenv()


@tool
async def consultar_cadastro_erp(documento: str) -> str:
    """
    Consulta o cadastro de um cliente no ERP a partir do CNPJ ou CPF.

    Args:
        documento: CNPJ ou CPF apenas com dígitos ou formatado.

    Returns:
        Resumo textual do cadastro (mock até integração real).
    """
    # Mock operacional: simula latência de sistema legado / rede.
    await asyncio.sleep(2)
    return "Status: Ativo, Cotas: 2"


def _criar_llm() -> ChatOpenAI:
    # ChatOpenAI lê OPENAI_API_KEY do ambiente automaticamente se não passarmos api_key.
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
    )


def criar_agente_executor() -> AgentExecutor:
    """
    Monta o agente com tools e um prompt mínimo para chamadas estruturadas (tool calling).
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
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
    )


async def executar_agente(
    mensagem_usuario: str,
    chat_history: list[Any] | None = None,
) -> dict[str, Any]:
    """
    Executa uma rodada do agente (assíncrono) — ponto de integração com API e WhatsApp.

    Args:
        mensagem_usuario: Texto da mensagem atual.
        chat_history: Histórico no formato aceito pelo prompt (lista de tuplas/mensagens).

    Returns:
        Dicionário com a saída do AgentExecutor (ex.: chave 'output').
    """
    executor = criar_agente_executor()
    return await executor.ainvoke(
        {
            "input": mensagem_usuario,
            "chat_history": chat_history or [],
        }
    )
