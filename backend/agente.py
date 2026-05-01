"""
Cérebro do CotaSync: agente LangChain com ChatOpenAI e tools operacionais.

Integração Streamlit: use `processar_mensagem` (assíncrona) ou `asyncio.run(...)` no app.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
from pydantic import BaseModel, Field

from backend.motor_browser import (
    acionar_ia_cartografa,
    consultar_erp_real,
    executar_acao_rapida,
    gerar_plano_acao,
)

load_dotenv()
_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _ROOT / "data"
os.makedirs(str(_DATA_DIR), exist_ok=True)
_UI_MAP_PATH = _DATA_DIR / "ui_map.json"
_LOG_DIR = _ROOT / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "operation.log"
_LOGGER = logging.getLogger("cotasync")
if not _LOGGER.handlers:
    _LOGGER.setLevel(logging.INFO)
    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _LOGGER.addHandler(file_handler)
    _LOGGER.propagate = False
sessoes_usuarios = {
    "admin": {
        "estado": "NORMAL",
        "acao_pendente": None,
        "checklist_pendente": [],
        "instrucao_original": "",
    }
}


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


async def gerar_nome_acao(instrucao: str) -> str:
    """
    Gera um nome curto e semântico para a ação aprendida.
    Retorna no máximo 4 palavras, sem aspas.
    """
    llm = _criar_llm()
    prompt = (
        "Resuma a instrução abaixo em um nome de ação curto e claro, com no máximo 4 palavras, "
        "sem aspas, sem pontuação final e sem explicações.\n\n"
        f"Instrução: {instrucao}"
    )
    try:
        resposta = await llm.ainvoke(prompt)
        nome = str(getattr(resposta, "content", "") or "").strip()
    except Exception:
        nome = ""

    if not nome:
        nome = "Nova Rotina"
    nome = nome.replace('"', "").replace("'", "").replace("\n", " ").strip()
    nome = re.sub(r"\s+", " ", nome)
    palavras = nome.split()
    if len(palavras) > 4:
        nome = " ".join(palavras[:4])
    return nome


async def revisar_e_otimizar_passos(objetivo: str, passos_brutos: list) -> list:
    """Passa o mapa bruto por uma revisão LLM para remover loops e redundâncias."""
    import logging

    # Se a rotina for muito curta, nem precisa gastar token revisando
    if len(passos_brutos) <= 2:
        return passos_brutos

    prompt_sistema = (
        "Você é um Engenheiro de Qualidade de RPA. "
        "Sua função é analisar uma lista de passos (JSON) gravados por um robô explorador e otimizá-la.\n"
        "Regras:\n"
        "1. Remova passos redundantes ou em loop (ex: a mesma ação no mesmo seletor repetida várias vezes sem necessidade, como múltiplos 'download_pdf' seguidos no mesmo botão).\n"
        "2. Mantenha a ordem cronológica estrita.\n"
        "3. Não altere o nome das ações, seletores ou variáveis.\n"
        "4. Retorne APENAS um array JSON válido com a lista de passos otimizada, sem marcações markdown ou texto extra."
    )

    prompt_usuario = (
        f"Objetivo da Rotina: {objetivo}\n\n"
        f"Passos Brutos (JSON):\n{json.dumps(passos_brutos, indent=2, ensure_ascii=False)}\n\n"
        "Retorne apenas o JSON otimizado."
    )

    try:
        from litellm import acompletion

        logging.info("[CARTÓGRAFO] Iniciando revisão e otimização do mapa com LLM...")
        response = await acompletion(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario},
            ],
            temperature=0.0,
        )

        conteudo = str(response.choices[0].message.content or "").strip()
        if conteudo.startswith("```json"):
            conteudo = conteudo[7:]
        if conteudo.endswith("```"):
            conteudo = conteudo[:-3]

        passos_otimizados = json.loads(conteudo.strip())
        if isinstance(passos_otimizados, list):
            logging.info(
                f"[CARTÓGRAFO] Mapa otimizado! Reduzido de {len(passos_brutos)} para {len(passos_otimizados)} passos."
            )
            return passos_otimizados
        return passos_brutos
    except Exception as e:
        logging.error(f"[CARTÓGRAFO] Erro na revisão do mapa, salvando versão bruta como fallback: {e}")
        return passos_brutos


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


async def processar_mensagem(mensagem_usuario: str, historico: list | None = None) -> Any:
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
    user_id = "admin"
    sessao = sessoes_usuarios.setdefault(
        user_id,
        {
            "estado": "NORMAL",
            "acao_pendente": None,
            "checklist_pendente": [],
            "instrucao_original": "",
        },
    )
    estado = str(sessao.get("estado", "NORMAL"))
    mensagem_normalizada = str(mensagem_usuario or "").lower()

    def _montar_resposta(texto: str, extras: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"texto": str(texto), "estado": str(sessoes_usuarios[user_id].get("estado", "NORMAL"))}
        if isinstance(extras, dict):
            payload.update(extras)
        return payload

    async def _executar_fluxo_aprendizado(sessao_atual: dict, instrucao_execucao: str) -> dict[str, Any]:
        sessao_atual["estado"] = "APRENDENDO"
        ui_map_atual = carregar_ui_map()
        acoes_existentes = ui_map_atual.get("acoes_conhecidas", {})
        nome_base = await gerar_nome_acao(sessao_atual.get("instrucao_original", instrucao_execucao))
        nome_acao = nome_base
        contador = 2
        while isinstance(acoes_existentes, dict) and nome_acao in acoes_existentes:
            nome_acao = f"{nome_base} {contador}"
            contador += 1
        sessao_atual["acao_pendente"] = nome_acao
        _LOGGER.info(f"[HITL] Estado APRENDENDO iniciado para ação: {nome_acao}")
        resultado_mapeamento = await acionar_ia_cartografa(
            nome_acao,
            instrucao_execucao,
            checklist_aprovada=sessao_atual.get("checklist_pendente", []),
        )
        status_mapeamento = (
            str(resultado_mapeamento.get("status", "")).lower()
            if isinstance(resultado_mapeamento, dict)
            else "erro"
        )
        if status_mapeamento != "sucesso":
            sessao_atual["estado"] = "ESPERANDO_ENSINO"
            motivo = (
                str(resultado_mapeamento.get("motivo", "Falha não identificada."))
                if isinstance(resultado_mapeamento, dict)
                else "Falha não identificada."
            )
            _LOGGER.info(f"[ERRO] Obstáculo encontrado. Solicitando intervenção humana no chat. Motivo: {motivo}")
            return _montar_resposta(
                "Chefe, tentei entrar no sistema com as credenciais cadastradas, mas parece que os dados "
                "estão incorretos ou o sistema pediu um CAPTCHA/Código que eu não consigo ver. "
                "Pode verificar as configurações ou me ajudar a passar dessa tela no 'Logs do Sistema'?"
            )

        passos_reais = resultado_mapeamento.get("passos_playwright") if isinstance(resultado_mapeamento, dict) else None
        if not isinstance(passos_reais, list) or not passos_reais:
            sessao_atual["estado"] = "ESPERANDO_ENSINO"
            _LOGGER.info(
                "[ERRO] Obstáculo encontrado. Solicitando intervenção humana no chat. "
                "Motivo: retorno de mapeamento sem passos_playwright."
            )
            return _montar_resposta(
                "Chefe, tentei entrar no sistema com as credenciais cadastradas, mas parece que os dados "
                "estão incorretos ou o sistema pediu um CAPTCHA/Código que eu não consigo ver. "
                "Pode verificar as configurações ou me ajudar a passar dessa tela no 'Logs do Sistema'?"
            )

        passos_reais = await revisar_e_otimizar_passos(instrucao_execucao, passos_reais)

        ui_map = carregar_ui_map()
        ui_map.setdefault("acoes_conhecidas", {})
        ui_map["acoes_conhecidas"][nome_acao] = {
            "nome_amigavel": nome_acao,
            "descricao": f"Ação aprendida: {str(sessao_atual.get('instrucao_original', instrucao_execucao))[:80]}...",
            "url_inicial": "Lida do erp_config.json",
            "passos_playwright": passos_reais,
            "variaveis_necessarias": (
                resultado_mapeamento.get("variaveis_necessarias", [])
                if isinstance(resultado_mapeamento, dict)
                else []
            ),
        }
        try:
            salvar_ui_map(ui_map)
        except OSError:
            sessao_atual["estado"] = "NORMAL"
            sessao_atual["acao_pendente"] = None
            sessao_atual["checklist_pendente"] = []
            sessao_atual["instrucao_original"] = ""
            return _montar_resposta(
                "Entendi o passo a passo, mas nao consegui salvar no ui_map.json agora. "
                "Pode tentar novamente em instantes?"
            )

        sessao_atual["estado"] = "NORMAL"
        sessao_atual["acao_pendente"] = None
        sessao_atual["checklist_pendente"] = []
        sessao_atual["instrucao_original"] = ""
        total_passos = len(passos_reais)
        dados_extraidos = (
            resultado_mapeamento.get("dados_extraidos", {})
            if isinstance(resultado_mapeamento, dict)
            else {}
        )
        resposta_base = (
            f"Aprendi {total_passos} passos para a rotina '{nome_acao}'. "
            "Já guardei os comandos técnicos no meu banco de dados."
        )
        if isinstance(dados_extraidos, dict) and dados_extraidos:
            arquivos_aprendizado = [
                str(valor)
                for valor in dados_extraidos.values()
                if isinstance(valor, str) and valor.startswith("downloads/")
            ]
            return _montar_resposta(
                (
                    f"Aprendi a rotina '{nome_acao}'. Além disso, extraí as seguintes informações do sistema: "
                    f"{dados_extraidos}"
                ),
                {"arquivos": arquivos_aprendizado, "dados_extraidos": dados_extraidos},
            )
        return _montar_resposta(resposta_base)

    if estado == "ESPERANDO_ENSINO":
        plano = await gerar_plano_acao(mensagem_usuario)
        plano = plano if isinstance(plano, list) and plano else [mensagem_usuario]
        sessoes_usuarios[user_id]["checklist_pendente"] = [str(tarefa) for tarefa in plano]
        sessoes_usuarios[user_id]["instrucao_original"] = mensagem_usuario
        sessoes_usuarios[user_id]["estado"] = "ESPERANDO_APROVACAO_PLANO"
        plano_formatado = "\n".join([f"{i + 1}. {tarefa}" for i, tarefa in enumerate(plano)])
        return _montar_resposta(
            f"📋 **Plano de Ação Criado:**\n{plano_formatado}\n\n"
            "Posso prosseguir com esta execução ou deseja corrigir algum passo?"
        )

    if estado == "ESPERANDO_APROVACAO_PLANO":
        class AvaliacaoPlano(BaseModel):
            aprovado: bool = Field(
                description=(
                    "True se o utilizador aprovou ou concordou (ex: ok, pode, sim, isso). "
                    "False se pediu correção."
                )
            )

        llm = _criar_llm()
        avaliador = llm.with_structured_output(AvaliacaoPlano)
        avaliacao = await avaliador.ainvoke(
            f"O utilizador avaliou o plano assim: '{mensagem_usuario}'. "
            "Ele está a aprovar (True) ou a corrigir/rejeitar (False)?"
        )

        if bool(getattr(avaliacao, "aprovado", False)):
            return await _executar_fluxo_aprendizado(sessao, str(sessao.get("instrucao_original", mensagem_usuario)))

        nova_instrucao = (
            f"Instrução original: {sessao.get('instrucao_original', '')}. "
            f"Correção pedida: {mensagem_usuario}"
        )
        novo_plano = await gerar_plano_acao(nova_instrucao)
        novo_plano = novo_plano if isinstance(novo_plano, list) and novo_plano else [nova_instrucao]
        sessoes_usuarios[user_id]["checklist_pendente"] = [str(tarefa) for tarefa in novo_plano]
        sessoes_usuarios[user_id]["instrucao_original"] = nova_instrucao

        plano_formatado = "\n".join([f"{i + 1}. {tarefa}" for i, tarefa in enumerate(novo_plano)])
        return _montar_resposta(f"🔄 **Plano Atualizado:**\n{plano_formatado}\n\nFicou bom agora? Posso executar?")

    if estado == "NORMAL":
        ui_map = carregar_ui_map()
        acoes = ui_map.get("acoes_conhecidas", {})
        mensagem_limpa = str(mensagem_usuario or "").strip()
        if isinstance(acoes, dict) and mensagem_limpa in acoes:
            _LOGGER.info(f"[FAST-TRACK] Disparo direto da ação: {mensagem_limpa}")
            acao = acoes.get(mensagem_limpa, {})
            passos = acao.get("passos_playwright", []) if isinstance(acao, dict) else []
            resultado_execucao = await executar_acao_rapida(mensagem_limpa, passos, None)
            if str(resultado_execucao.get("status", "")).lower() == "sucesso":
                arquivos_baixados = resultado_execucao.get("arquivos_baixados", [])
                evidencia = str(resultado_execucao.get("evidencia", ""))
                dados_ft = resultado_execucao.get("dados_extraidos", {})
                extras: dict[str, Any] = {
                    "evidencia": evidencia,
                    "arquivos": arquivos_baixados if isinstance(arquivos_baixados, list) else [],
                }
                if isinstance(dados_ft, dict) and dados_ft:
                    extras["dados_extraidos"] = dados_ft
                return _montar_resposta(
                    "✅ Execução concluída com sucesso! Evidência visual e arquivos extraídos abaixo:",
                    extras,
                )
            motivo = str(resultado_execucao.get("motivo", "Falha não identificada."))
            return _montar_resposta(f"❌ A execução rápida falhou: {motivo}")

        if "ensinar" in mensagem_normalizada or "aprender" in mensagem_normalizada:
            sessao["estado"] = "ESPERANDO_ENSINO"
            sessao["acao_pendente"] = "nova_acao"
            _LOGGER.info("[HITL] Estado ESPERANDO_ENSINO para ação pendente genérica.")
            return _montar_resposta(
                "🎓 **Modo de Aprendizado ativado!**\n\n"
                "Por favor, descreva o passo a passo da tarefa que deseja mapear. \n"
                "*Exemplo: 'Preencha a busca com 123, clique em Pesquisar e extraia o valor total'.*"
            )

    chat_history = _historico_dicts_para_mensagens(historico)
    executor = criar_agente_executor()
    resultado = await executor.ainvoke(
        {
            "input": mensagem_usuario,
            "chat_history": chat_history,
        }
    )
    return _montar_resposta(str(resultado.get("output", "")).strip())


async def executar_acao_fast_track(
    nome_acao: str,
    dados_variaveis: dict | None = None,
) -> dict[str, Any]:
    ui_map = carregar_ui_map()
    acoes = ui_map.get("acoes_conhecidas", {})
    if not isinstance(acoes, dict) or nome_acao not in acoes:
        return {"texto": f"❌ A ação '{nome_acao}' não foi encontrada.", "estado": "NORMAL"}

    acao = acoes.get(nome_acao, {})
    passos_playwright = acao.get("passos_playwright", []) if isinstance(acao, dict) else []

    try:
        resultado = await executar_acao_rapida(
            nome_acao,
            passos_playwright,
            dados_variaveis if isinstance(dados_variaveis, dict) else None,
        )
        if str(resultado.get("status", "")).lower() != "sucesso":
            motivo = str(resultado.get("motivo", "Falha não identificada."))
            raise RuntimeError(motivo)
        return {
            "texto": "✅ Execução rápida concluída com sucesso da memória!",
            "estado": "NORMAL",
            "evidencia": str(resultado.get("evidencia", "")),
            "arquivos": resultado.get("arquivos_baixados", []),
            "dados_extraidos": resultado.get("dados_extraidos", {}),
        }

    except Exception as erro_fast_track:
        logging.warning(f"[AUTO-HEALING] Fast-Track falhou para a ação '{nome_acao}'. Erro: {erro_fast_track}")
        logging.info("[AUTO-HEALING] Acionando a IA para Diagnóstico e Correção da tela...")

        instrucao_recuperacao = f"""
        A rotina mapeada '{nome_acao}' falhou ao ser repetida com o erro: {str(erro_fast_track)}.
        DIAGNÓSTICO OBRIGATÓRIO:
        1. Olhe para a tela atual. O sistema alvo está apenas lento (ex: ícone a carregar, erro 504/503) ou apareceu um popup/aviso bloqueador normal do sistema?
        2. Se for um erro temporário ou popup, feche o aviso ou clique em atualizar e tente concluir a tarefa com os seletores originais.
        3. Apenas se a interface realmente MUDOU de estrutura (o botão desapareceu definitivamente), encontre o novo botão/caminho.
        Conclua a tarefa original de '{nome_acao}' e atualize a receita dos passos.
        """

        try:
            novos_passos = await acionar_ia_cartografa(nome_acao, instrucao_recuperacao)

            memoria = carregar_ui_map()
            memoria.setdefault("acoes_conhecidas", {})
            memoria["acoes_conhecidas"].setdefault(nome_acao, {})
            memoria["acoes_conhecidas"][nome_acao]["passos_playwright"] = novos_passos.get("passos_playwright", [])
            salvar_ui_map(memoria)

            logging.info(f"[AUTO-HEALING] SUCESSO! A rotina '{nome_acao}' foi auto-corrigida.")

            return {
                "texto": (
                    "⚠️ **Diagnóstico e Auto-Correção:** Ocorreu um obstáculo no sistema (possível lentidão ou mudança de tela).\n\n"
                    "Assumi o controlo manual com a Inteligência Artificial, analisei a situação, concluí a tarefa pretendida "
                    "e ajustei a minha abordagem para não falhar na próxima!\n\n"
                    f"Dados extraídos: {novos_passos.get('dados_extraidos', {})}"
                ),
                "estado": "NORMAL",
                "arquivos": novos_passos.get("arquivos_baixados", []),
                "dados_extraidos": novos_passos.get("dados_extraidos", {}),
            }

        except Exception as e_ia:
            logging.error(f"[AUTO-HEALING FALHOU] {str(e_ia)}")
            return {
                "texto": (
                    "❌ **Falha Crítica:** O sistema parece estar indisponível ou ocorreu um erro incontornável. "
                    "Tentei assumir o controlo manual com a IA, mas não foi possível avançar. "
                    f"Erro técnico: {str(e_ia)}"
                ),
                "estado": "NORMAL",
            }


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
