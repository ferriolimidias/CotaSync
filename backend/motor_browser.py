"""
Motor físico de automação web: Playwright conectado ao Browserless via CDP.

O Browserless expõe um endpoint WebSocket para Chromium remoto; aqui usamos
`connect_over_cdp` para anexar uma sessão ao cluster sem gerenciar binários localmente.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
import pandas as pd
from pydantic import BaseModel, Field
from playwright.async_api import Browser, async_playwright

load_dotenv()
os.makedirs("data", exist_ok=True)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Nome do ficheiro de evidência na raiz do projeto (alinhado ao Streamlit e à tool do agente).
NOME_ARQUIVO_EVIDENCIA = "data/print_teste.png"
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "operation.log"
_LOGGER = logging.getLogger("cotasync")
if not _LOGGER.handlers:
    _LOGGER.setLevel(logging.INFO)
    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _LOGGER.addHandler(file_handler)
    _LOGGER.propagate = False


class PassoCartografo(BaseModel):
    raciocinio: str = Field(description="Explicação curta do próximo passo.")
    tipo: Literal["clicar", "preencher", "teclar", "extrair_texto", "download_pdf", "concluido"] = Field(
        description="Tipo da ação a executar."
    )
    seletor: str = Field(default="", description="Seletor CSS preciso do elemento.")
    valor: str = Field(default="", description="Valor opcional para preencher ou referência textual.")


class PlanoAcao(BaseModel):
    checklist: list[str] = Field(description="Lista de tarefas técnicas claras e isoladas.")


def _carregar_erp_config() -> tuple[str, str, str]:
    raiz = _raiz_projeto()
    erp_config_path = raiz / "data" / "erp_config.json"
    url_sistema = "https://google.com"
    usuario = ""
    senha = ""
    try:
        if erp_config_path.is_file():
            config = json.loads(erp_config_path.read_text(encoding="utf-8"))
            if isinstance(config, dict):
                url_sistema = str(config.get("url_sistema") or url_sistema).strip() or url_sistema
                usuario = str(config.get("usuario") or "").strip()
                senha = str(config.get("senha") or "")
    except (json.JSONDecodeError, OSError):
        pass
    return url_sistema, usuario, senha


async def _login_automatico(page: Any, url_sistema: str, usuario: str, senha: str) -> tuple[bool, str]:
    _LOGGER.info("[LOGIN] Abrindo página inicial do ERP...")
    await page.goto(url_sistema, wait_until="networkidle")
    _LOGGER.info(f"[LOGIN] Página carregada em: {page.url}")

    has_password = await page.locator("input[type='password'], #pass").count() > 0
    has_login_field = (
        await page.locator("input[name='login'], input[name='username'], input[name='usuario'], #user").count() > 0
    )
    if not (has_password or has_login_field):
        return True, "Sem tela de login detectada."

    _LOGGER.info("[CARTÓGRAFO] Página de login detectada. Realizando login automático com credenciais configuradas...")
    _LOGGER.info("[LOGIN] Tentando autenticação automática...")
    usuario_sel = "#user, input[name='login'], input[name='username'], input[name='usuario'], input[type='email'], input[type='text']"
    senha_sel = "#pass, input[type='password']"

    if await page.locator(usuario_sel).count() > 0:
        await page.locator(usuario_sel).first.fill(usuario)
        _LOGGER.info("[LOGIN] Campo de usuário preenchido.")
    else:
        _LOGGER.info("[ERRO] Campo de usuário não encontrado.")

    if await page.locator(senha_sel).count() > 0:
        await page.locator(senha_sel).first.fill(senha)
        _LOGGER.info("[LOGIN] Campo de senha preenchido.")
    else:
        _LOGGER.info("[ERRO] Campo de senha não encontrado.")

    botao_login = ""
    if await page.locator("#login-button").count() > 0:
        botao_login = "#login-button"
    elif await page.locator("button[type='submit']").count() > 0:
        botao_login = "button[type='submit']"
    elif await page.locator("button").count() > 0:
        botao_login = "button"
    else:
        return False, "Botão de login não encontrado na página."

    _LOGGER.info(f"[LOGIN] Clicando em '{botao_login}' para autenticar.")
    await page.click(botao_login)
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        _LOGGER.info("[LOGIN] Network idle não confirmado; continuando validação visual do DOM.")
    await asyncio.sleep(2)

    try:
        login_ainda_visivel = await page.is_visible(botao_login)
    except Exception:
        login_ainda_visivel = False

    if login_ainda_visivel:
        textos_erro = await page.evaluate(
            """() => {
                const elementos = Array.from(document.querySelectorAll('div, span, p'));
                const erros = elementos.filter(el => {
                    const texto = (el.innerText || '').toLowerCase();
                    const estilo = window.getComputedStyle(el);
                    const classe = typeof el.className === 'string' ? el.className.toLowerCase() : '';
                    return (texto.includes('erro') ||
                            texto.includes('incorreto') ||
                            texto.includes('inválido') ||
                            texto.includes('invalido')) &&
                           (estilo.color === 'rgb(255, 0, 0)' || classe.includes('red') || classe.includes('error'));
                });
                return erros.length > 0 ? erros[0].innerText : "Mensagem de erro não identificada no DOM.";
            }"""
        )
        msg_falha = (
            "Login falhou. A tela de login ainda está visível. "
            f"Possível erro do sistema: {textos_erro}"
        )
        _LOGGER.warning(f"[ERRO] {msg_falha}")
        raise Exception(msg_falha)

    _LOGGER.info("[LOGIN] Autenticação bem-sucedida.")
    return True, "Login concluído."


async def _extrair_mapa_dom(page: Any, limite: int = 80) -> list[dict[str, str]]:
    mapa_dom = await page.evaluate(
        """
        (limite) => {
          const limpos = Array.from(
            document.querySelectorAll("button, a, input, [role='button'], p, span, td, h1, h2, h3, label, [id]")
          )
          .filter((e) => {
            const style = window.getComputedStyle(e);
            return (
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              style.opacity !== "0" &&
              e.offsetWidth > 0 &&
              e.offsetHeight > 0
            );
          })
          .map((e) => {
            const tagName = (e.tagName || "").toLowerCase();
            let textoReal = "";
            if (tagName === "input" || tagName === "textarea") {
              textoReal = e.value || e.placeholder || "";
            } else {
              textoReal = e.innerText || "";
            }
            textoReal = (textoReal || "").trim().substring(0, 80);
            return {
              tag: tagName,
              text: textoReal,
              texto: textoReal,
              id: (e.id || "").trim(),
              className: typeof e.className === "string" ? e.className.trim() : "",
              name: (e.getAttribute("name") || "").trim(),
              href: (e.getAttribute("href") || "").trim(),
              placeholder: (e.getAttribute("placeholder") || "").trim(),
            };
          })
          .filter((item) => item.text.length > 0 || item.id);
          return limpos.slice(0, limite);
        }
        """,
        limite,
    )
    if not isinstance(mapa_dom, list):
        return []
    resultado: list[dict[str, str]] = []
    for item in mapa_dom:
        if not isinstance(item, dict):
            continue
        if not (item.get("texto") or item.get("id") or item.get("name") or item.get("placeholder")):
            continue
        resultado.append(
            {
                "tag": str(item.get("tag", "")),
                "texto": str(item.get("texto", "")),
                "id": str(item.get("id", "")),
                "name": str(item.get("name", "")),
                "href": str(item.get("href", "")),
                "placeholder": str(item.get("placeholder", "")),
            }
        )
    return resultado[:limite]


def _raiz_projeto() -> Path:
    return Path(__file__).resolve().parent.parent


def _ws_browserless() -> str:
    """
    URL WebSocket do Browserless. No Docker Compose usamos `ws://browserless:3000`;
    em desenvolvimento local, `BROWSERLESS_URL=ws://localhost:3000` no `.env`.
    """
    ws_url = os.getenv("BROWSERLESS_URL", "ws://localhost:3000").strip()
    if not ws_url.startswith("ws"):
        ws_url = ws_url.replace("http://", "ws://").replace("https://", "wss://")
    return ws_url


def _carregar_ui_map() -> dict:
    caminho = _DATA_DIR / "ui_map.json"
    if not caminho.is_file():
        return {"acoes_conhecidas": {}}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            return {"acoes_conhecidas": {}}
        if not isinstance(dados.get("acoes_conhecidas"), dict):
            dados["acoes_conhecidas"] = {}
        return dados
    except (json.JSONDecodeError, OSError):
        return {"acoes_conhecidas": {}}


def _converter_pdf_para_excel(caminho_pdf: str) -> str:
    """Extrai tabelas de um PDF e salva como ficheiro Excel (.xlsx)."""
    import logging

    import pandas as pd
    try:
        import pdfplumber
    except ImportError:
        logging.error("[CONVERSÃO] Biblioteca pdfplumber não instalada.")
        return caminho_pdf

    caminho_excel = caminho_pdf.replace(".pdf", ".xlsx")
    dados = []

    try:
        if not _arquivo_pdf_pronto_e_integro(caminho_pdf, timeout_segundos=45):
            logging.error(f"[CONVERSÃO] PDF inválido/incompleto: {caminho_pdf}")
            return caminho_pdf

        with pdfplumber.open(caminho_pdf) as pdf:
            for pagina in pdf.pages:
                tabelas = pagina.extract_tables()
                for tabela in tabelas:
                    for linha in tabela:
                        dados.append([str(c).replace("\n", " ").strip() if c else "" for c in linha])

        if dados:
            df = pd.DataFrame(dados)
            df.to_excel(caminho_excel, index=False, header=False)
            logging.info(f"[CONVERSÃO] PDF convertido para Excel com sucesso: {caminho_excel}")
            return caminho_excel
        else:
            logging.warning(f"[CONVERSÃO] Nenhuma tabela estruturada encontrada no PDF: {caminho_pdf}")
            return caminho_pdf

    except Exception as e:
        logging.error(f"[CONVERSÃO] Erro crítico ao converter {caminho_pdf}: {e}")
        return caminho_pdf


def _arquivo_pdf_pronto_e_integro(caminho_pdf: str, timeout_segundos: int = 45) -> bool:
    """Espera arquivo estabilizar e valida assinatura básica de PDF."""
    inicio = time.time()
    tamanho_anterior = -1
    repeticoes_mesmo_tamanho = 0

    logging.info(f"[DOWNLOAD] Aguardando arquivo no disco: {caminho_pdf}")
    while (time.time() - inicio) < timeout_segundos:
        if os.path.exists(caminho_pdf):
            tamanho_atual = os.path.getsize(caminho_pdf)
            logging.info(f"[DOWNLOAD] Download em andamento... tamanho atual: {tamanho_atual} bytes")
            if tamanho_atual > 0:
                if tamanho_atual == tamanho_anterior:
                    repeticoes_mesmo_tamanho += 1
                else:
                    repeticoes_mesmo_tamanho = 0
                tamanho_anterior = tamanho_atual
                if repeticoes_mesmo_tamanho >= 1:
                    break
        time.sleep(1)

    if not os.path.exists(caminho_pdf):
        logging.error(f"[DOWNLOAD] Timeout: arquivo não apareceu em disco: {caminho_pdf}")
        return False

    tamanho_final = os.path.getsize(caminho_pdf)
    if tamanho_final <= 1024:
        logging.error(f"[DOWNLOAD] Arquivo muito pequeno para PDF válido ({tamanho_final} bytes): {caminho_pdf}")
        return False

    try:
        with open(caminho_pdf, "rb") as f:
            assinatura = f.read(5)
        if assinatura != b"%PDF-":
            logging.error(f"[DOWNLOAD] Assinatura inválida para PDF em {caminho_pdf}: {assinatura!r}")
            return False
    except OSError as exc:
        logging.error(f"[DOWNLOAD] Erro ao validar PDF {caminho_pdf}: {exc}")
        return False

    logging.info(f"[DOWNLOAD] Download concluído, tamanho: {tamanho_final} bytes")
    return True


async def _aguardar_arquivo_estavel(caminho_arquivo: str, timeout_segundos: int = 45) -> bool:
    """Polling assíncrono para garantir término da escrita no disco."""
    inicio = time.time()
    tamanho_anterior = -1
    repeticoes_mesmo_tamanho = 0

    logging.info(f"[DOWNLOAD] Aguardando início do download em: {caminho_arquivo}")
    while (time.time() - inicio) < timeout_segundos:
        if os.path.exists(caminho_arquivo):
            tamanho_atual = os.path.getsize(caminho_arquivo)
            logging.info(f"[DOWNLOAD] Download em andamento... tamanho atual: {tamanho_atual} bytes")
            if tamanho_atual > 0:
                if tamanho_atual == tamanho_anterior:
                    repeticoes_mesmo_tamanho += 1
                else:
                    repeticoes_mesmo_tamanho = 0
                tamanho_anterior = tamanho_atual
                if repeticoes_mesmo_tamanho >= 1:
                    logging.info(f"[DOWNLOAD] Download concluído, tamanho: {tamanho_atual} bytes")
                    return True
        await asyncio.sleep(1)

    logging.error(f"[DOWNLOAD] Timeout ao aguardar escrita completa: {caminho_arquivo}")
    return False


async def processar_lote_com_semaforo(
    chave_acao: str,
    lista_linhas: list[dict],
    mapeamento: dict,
    max_concorrencia: int = 5,
) -> list[dict]:
    """
    Processa uma lista de dados (linhas do Excel) de forma assíncrona e controlada.
    Limita a abertura simultânea de abas no Browserless usando asyncio.Semaphore.
    """
    semaforo = asyncio.Semaphore(max_concorrencia)
    memoria = _carregar_ui_map()

    if chave_acao not in memoria.get("acoes_conhecidas", {}):
        raise ValueError(f"Ação {chave_acao} não encontrada na memória.")

    passos_playwright = memoria["acoes_conhecidas"][chave_acao].get("passos_playwright", [])

    async def worker(index: int, linha_dados: dict):
        async with semaforo:
            dados_variaveis = {}
            for var_json, col_excel in mapeamento.items():
                dados_variaveis[var_json] = str(linha_dados.get(col_excel, ""))

            try:
                logging.info(f"[LOTE] Iniciando linha {index}...")
                resultado = await executar_acao_rapida(
                    chave_acao,
                    passos_playwright,
                    dados_variaveis,
                )
                textos_extraidos = str(resultado.get("dados_extraidos", "")) if resultado.get("dados_extraidos") else ""

                return {
                    "indice_original": index,
                    "Status_Robo": "Sucesso",
                    "Detalhes_Erro": "",
                    "Dados_Extraidos": textos_extraidos,
                    "Evidencia": resultado.get("evidencia", ""),
                }
            except Exception as e:
                logging.error(f"[LOTE] Erro na linha {index}: {str(e)}")
                return {
                    "indice_original": index,
                    "Status_Robo": "Erro",
                    "Detalhes_Erro": str(e),
                    "Dados_Extraidos": "",
                    "Evidencia": "",
                }

    tasks = [worker(idx, linha) for idx, linha in enumerate(lista_linhas)]
    resultados = await asyncio.gather(*tasks)
    resultados.sort(key=lambda x: x["indice_original"])
    return resultados


async def consultar_erp_real(cnpj: str) -> dict[str, Any]:
    """
    Navegação real de validação: Wikipedia PT + busca + screenshot na raiz do projeto.

    Nota: o parâmetro é tratado como texto de busca (ex.: CNPJ) para o campo da wiki.
    """
    raiz = _raiz_projeto()
    caminho_imagem = _DATA_DIR / "print_teste.png"
    ws_url = _ws_browserless()
    browser: Browser | None = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(ws_url)
            try:
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = await context.new_page()
                await page.set_default_timeout(90_000)

                await page.goto(
                    "https://pt.wikipedia.org/wiki/Consórcio",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_selector('input[name="search"]', state="visible")
                await page.fill('input[name="search"]', cnpj)
                await page.keyboard.press("Enter")
                # A Wikipédia mantém ligações longas; `networkidle` pode não ocorrer de forma fiável.
                try:
                    await page.wait_for_load_state("networkidle", timeout=45_000)
                except Exception:
                    await page.wait_for_load_state("domcontentloaded")

                await page.screenshot(path=str(caminho_imagem), full_page=False)
                titulo = await page.title()

                return {
                    "status": "sucesso",
                    "texto_extraido": titulo,
                    "caminho_imagem": "data/print_teste.png",
                }
            finally:
                if browser is not None:
                    await browser.close()
    except Exception as e:
        # Log no terminal (uvicorn / streamlit) para diagnóstico rápido.
        _LOGGER.info(f"[PLAYWRIGHT] Erro no Playwright: {e}")
        return {
            "status": "erro",
            "texto_extraido": f"Erro técnico: {str(e)}",
            "caminho_imagem": "",
        }


async def obter_browser_browserless() -> tuple[Any, Browser]:
    """
    Inicia o Playwright e conecta ao Chromium remoto (Browserless).

    Returns:
        Tupla (playwright_instance, browser) para que o chamador possa fazer
        `await playwright.stop()` após uso, se necessário.
    """
    ws_url = _ws_browserless()

    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(ws_url)
    return playwright, browser


async def exemplo_navegacao(url: str = "https://example.com") -> str:
    """
    Exemplo mínimo: abre uma página e retorna o título (útil para validar o pipeline).

    Futuro: aqui entrará o fluxo guiado por `ui_map.json` na raiz do projeto.
    ---------------------------------------------------------------------------
    INTERPRETAÇÃO FUTURA DO ui_map.json
    ---------------------------------------------------------------------------
    O arquivo `ui_map.json` descreverá "ações conhecidas" (chaves em
    `acoes_conhecidas`) mapeando cada operação de negócio para uma sequência
    declarativa de passos de UI (seletores CSS/XPath, esperas, preenchimento de
    campos, cliques e checkpoints). O motor em `motor_browser.py` deverá:

    1. Carregar e validar o JSON (Pydantic ou schema leve) no startup ou sob cache.
    2. Receber do agente LangChain ou do backend o *nome da ação* + parâmetros
       (ex.: credenciais em cofre, CNPJ, datas).
    3. Resolver a cadeia de passos da ação, instanciando `BrowserContext`/`Page`
       reutilizando a sessão Browserless quando fizer sentido (pool de contextos).
    4. Aplicar retries com backoff em falhas transitórias de rede/DOM e registrar
       evidências (screenshots/HTML snippet) para auditoria operacional.

    Enquanto isso não existe, mantemos apenas a conexão CDP e este comentário como
    âncora de arquitetura para não acoplar scraping ad-hoc ao restante do sistema.
    ---------------------------------------------------------------------------
    """
    pw, browser = await obter_browser_browserless()
    try:
        contexts = browser.contexts
        context = contexts[0] if contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        return await page.title()
    finally:
        await browser.close()
        await pw.stop()


async def gerar_plano_acao(instrucao_humana: str) -> list[str]:
    logging.info("[PLANEJADOR] A criar checklist de tarefas...")
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
        api_key=os.getenv("OPENAI_API_KEY") or None,
    )
    llm_planejador = llm.with_structured_output(PlanoAcao)
    prompt_plano = (
        f"Instrução do utilizador: '{instrucao_humana}'. "
        "Divida numa lista de tarefas técnicas claras e isoladas."
    )
    try:
        plano = await llm_planejador.ainvoke(prompt_plano)
        checklist = getattr(plano, "checklist", [])
        if isinstance(checklist, list) and checklist:
            return [str(item) for item in checklist if str(item).strip()]
        return [instrucao_humana]
    except Exception as e:
        logging.warning(f"Erro no planeador: {e}")
        return [instrucao_humana]


async def acionar_ia_cartografa(
    nome_acao: str,
    instrucao_humana: str,
    checklist_aprovada: list[str] | None = None,
) -> dict:
    """Acessa o ERP, faz login e aprende via loop semântico iterativo (Reason + Act)."""
    raiz = _raiz_projeto()
    url_sistema, usuario, senha = _carregar_erp_config()
    variaveis_mock = re.findall(r"\{(.*?)\}", instrucao_humana)
    instrucao_limpa = re.sub(r"\{(.*?)\}", r"\1", instrucao_humana)
    checklist_base = checklist_aprovada if checklist_aprovada else [instrucao_limpa]
    checklist_original = [re.sub(r"\{(.*?)\}", r"\1", str(item)) for item in checklist_base]
    objetivo_checklist = " | ".join(str(item) for item in checklist_original if str(item).strip()) or instrucao_limpa
    nome_arquivo = nome_acao.replace(" ", "_").replace("/", "_").replace("\\", "_")
    screenshot_path = _DATA_DIR / f"mapeamento_{nome_arquivo}.png"
    passos_aprendidos: list[dict[str, str]] = []
    dados_extraidos: dict[str, str] = {}
    erros_recentes: list[str] = []
    seletores_banidos: set[str] = set()

    browser: Browser | None = None
    _LOGGER.info(f"[CARTÓGRAFO] Acedendo a {url_sistema} para mapear a ação: {nome_acao}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("ws://browserless:3000")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            try:
                login_ok, login_msg = await _login_automatico(page, url_sistema, usuario, senha)
            except Exception as exc:
                return {"status": "erro", "motivo": str(exc)}
            if not login_ok:
                return {"status": "erro", "motivo": login_msg}
            _LOGGER.info(f"[LOGIN] {login_msg} Iniciando busca por: {instrucao_limpa}")

            llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0,
                api_key=os.getenv("OPENAI_API_KEY") or None,
            )
            llm_estruturado = llm.with_structured_output(PassoCartografo)

            for iteracao in range(10):
                mapa_dom = await _extrair_mapa_dom(page, limite=80)
                if not mapa_dom:
                    return {"status": "erro", "motivo": "Nao consegui extrair elementos interativos da tela atual."}

                prompt = (
                    f"Objetivo final: {instrucao_limpa}\n"
                    f"Checklist aprovada: {json.dumps(checklist_original, ensure_ascii=False)}\n"
                    f"Objetivo operacional consolidado: {objetivo_checklist}\n"
                    f"Passos já dados com sucesso: {json.dumps(passos_aprendidos, ensure_ascii=False)}\n"
                    f"Dados já extraídos: {json.dumps(dados_extraidos, ensure_ascii=False)}\n"
                    f"ERROS RECENTES (Evite repetir estas ações): {json.dumps(erros_recentes, ensure_ascii=False)}\n"
                    f"DOM atual: {json.dumps(mapa_dom, ensure_ascii=False)}\n\n"
                    "INSTRUÇÕES DO AGENTE:\n"
                    "1. Analise o DOM. Se ocorreu um erro no passo anterior, tente uma estratégia ou seletor diferente.\n"
                    "2. Ações permitidas: 'clicar', 'preencher', 'teclar', 'extrair_texto', 'download_pdf', 'concluido'.\n"
                    "3. REGRA CRÍTICA DE DOWNLOAD: Se o objetivo envolve 'baixar', 'download', 'PDF', 'fatura' ou "
                    "'boleto', e você encontrar o botão correspondente, VOCÊ É OBRIGADO a usar a ação 'download_pdf'. "
                    "NUNCA use 'clicar' para baixar ficheiros.\n"
                    "4. REGRA DE COMPLETUDE (MUITO IMPORTANTE): NUNCA utilize o tipo 'concluido' antes de ter cumprido "
                    "TODAS as ações solicitadas na instrução final. Se o utilizador pediu para preencher, extrair um "
                    "texto E baixar um ficheiro, você DEVE realizar essas 3 ações em iterações diferentes. Só use "
                    "'concluido' quando tiver a certeza absoluta de que NADA faltou.\n"
                    "5. REGRA DE EXTRAÇÃO (FOCAR NO VALOR): Diferencie Rótulos (Labels) de Valores Reais. NUNCA "
                    "utilize 'extrair_texto' no título do campo. Procure sempre o VALOR que o preenche. Exemplo: Se "
                    "procura um Status e vê no DOM 'Situação da Cota' (rótulo) e 'Ativa' (valor), o seu seletor DEVE "
                    "apontar para o valor (ex: 'text=Ativa' ou o seu ID). Seja perspicaz para apontar o seletor "
                    "nativo do Playwright para o dado numérico ou textual real que o utilizador deseja.\n"
                    "6. Qual é o ÚNICO PRÓXIMO PASSO lógico? Se o objetivo já foi atingido, use 'concluido'."
                )
                try:
                    decisao_ia = await llm_estruturado.ainvoke(prompt)
                except Exception as exc:
                    return {"status": "erro", "motivo": f"Falha na análise semântica da IA: {exc}"}

                if decisao_ia.tipo != "concluido" and decisao_ia.seletor:
                    if decisao_ia.seletor in seletores_banidos:
                        msg = (
                            f"AÇÃO BLOQUEADA: O seletor '{decisao_ia.seletor}' já falhou e está BANIDO nesta sessão. "
                            "Leia o DOM com atenção e use um ID real ou a busca por texto exato 'text=Valor'."
                        )
                        logging.warning(f"[ANTI-LOOP] Tentativa de usar seletor banido: {decisao_ia.seletor}")
                        erros_recentes.append(msg)
                        continue

                # --- ESCUDO ANTI-LOOP DE EXTRAÇÃO REPETIDA ---
                if decisao_ia.tipo == "extrair_texto" and decisao_ia.seletor in dados_extraidos:
                    msg = (
                        f"AÇÃO BLOQUEADA: O seletor '{decisao_ia.seletor}' já foi extraído com sucesso nesta sessão "
                        f"(Valor obtido: '{dados_extraidos[decisao_ia.seletor]}'). Se a tarefa continua pendente, "
                        "significa que você extraiu a informação inútil (ex: extraiu o título do campo em vez do "
                        "dado real). Leia o DOM e escolha OUTRO seletor que contenha o VALOR verdadeiro."
                    )
                    logging.warning(f"[ANTI-LOOP EXTRAÇÃO] Tentativa repetida bloqueada: {decisao_ia.seletor}")
                    erros_recentes.append(msg)
                    continue

                tipo = str(getattr(decisao_ia, "tipo", "") or "").strip().lower()
                seletor = str(getattr(decisao_ia, "seletor", "") or "").strip()
                valor = str(getattr(decisao_ia, "valor", "") or "").strip()
                raciocinio = str(getattr(decisao_ia, "raciocinio", "") or "").strip()
                _LOGGER.info(
                    f"[IA SEMÂNTICA] Iteração {iteracao + 1} | Raciocínio: {raciocinio} | "
                    f"Decisão: {tipo} no seletor {seletor}"
                )

                if decisao_ia.tipo == "concluido":
                    _LOGGER.info("[IA SEMÂNTICA] Objetivo marcado como concluído.")
                    break
                
                # --- ESCUDO ANTI-TEIMOSIA (Bloqueio em Python) ---
                if decisao_ia.tipo != "concluido" and decisao_ia.seletor:
                    if decisao_ia.seletor in seletores_banidos:
                        msg_bloqueio = (
                            f"AÇÃO BLOQUEADA PELO SISTEMA: O seletor '{decisao_ia.seletor}' já falhou nesta sessão. "
                            "É ESTRITAMENTE PROIBIDO repeti-lo. Olhe o mapa do DOM atual e escolha um 'id' ou 'class' "
                            "real que esteja na lista, ou use 'concluido'."
                        )
                        logging.warning(f"[ANTI-LOOP] Bloqueada tentativa de repetir: {decisao_ia.seletor}")
                        erros_recentes.append(msg_bloqueio)
                        continue

                if tipo in {"clicar", "preencher", "extrair_texto", "download_pdf"} and not seletor:
                    return {"status": "erro", "motivo": "A IA não retornou seletor válido para o próximo passo."}
                if tipo in {"preencher", "teclar"} and not valor:
                    return {"status": "erro", "motivo": f"A IA não retornou valor para ação '{tipo}'."}

                try:
                    if decisao_ia.tipo == "clicar":
                        elementos = page.locator(decisao_ia.seletor)
                        quantidade = await elementos.count()
                        sucesso_clique = False

                        try:
                            async with page.expect_popup(timeout=3000) as popup_info:
                                for i in range(quantidade):
                                    if await elementos.nth(i).is_visible():
                                        await elementos.nth(i).click(timeout=5000)
                                        sucesso_clique = True
                                        break
                                if not sucesso_clique:
                                    await elementos.first.click(timeout=5000, force=True)

                            nova_aba = await popup_info.value
                            try:
                                await nova_aba.wait_for_load_state("networkidle", timeout=5000)
                            except Exception:
                                pass

                            page = nova_aba
                            logging.info(f"[NAVEGAÇÃO] Popup/Nova Aba detetada! Foco transferido para: {page.url}")

                        except Exception:
                            if not sucesso_clique:
                                try:
                                    await elementos.first.click(timeout=5000, force=True)
                                except Exception:
                                    pass

                            try:
                                await page.wait_for_load_state("networkidle", timeout=3000)
                            except Exception:
                                pass

                        await asyncio.sleep(2)
                    elif tipo == "preencher":
                        await page.fill(seletor, valor)
                        await page.wait_for_timeout(500)
                    elif tipo == "teclar":
                        await page.keyboard.press(valor)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            await page.wait_for_timeout(800)
                        await asyncio.sleep(1.5)
                    elif tipo == "extrair_texto":
                        elemento = page.locator(seletor).first
                        tag_name = await elemento.evaluate("el => el.tagName.toLowerCase()")
                        if tag_name in ["input", "textarea"]:
                            texto = await elemento.input_value(timeout=5000)
                            if not texto:
                                texto = await elemento.get_attribute("value", timeout=5000) or ""
                        else:
                            texto = await elemento.inner_text(timeout=5000)
                        dados_extraidos[seletor] = texto
                        logging.info(f"[EXTRAÇÃO] Dado extraído: {texto}")
                    elif tipo == "download_pdf":
                        os.makedirs("downloads", exist_ok=True)
                        downloads_dir = raiz / "downloads"
                        downloads_dir.mkdir(parents=True, exist_ok=True)
                        async with page.expect_download(timeout=60000) as download_info:
                            elementos = page.locator(seletor)
                            quantidade = await elementos.count()
                            sucesso_clique = False

                            for i in range(quantidade):
                                if await elementos.nth(i).is_visible():
                                    await elementos.nth(i).click(timeout=5000)
                                    sucesso_clique = True
                                    break

                            if not sucesso_clique:
                                await elementos.first.click(timeout=5000, force=True)
                        download = await download_info.value
                        caminho_arquivo = downloads_dir / download.suggested_filename
                        await download.save_as(str(caminho_arquivo))
                        await _aguardar_arquivo_estavel(str(caminho_arquivo), timeout_segundos=45)
                        chave = f"arquivo_{seletor}"
                        dados_extraidos[chave] = str(caminho_arquivo.relative_to(raiz))
                        _LOGGER.info(f"[DOWNLOAD] Ficheiro salvo em: {caminho_arquivo}")
                    else:
                        return {"status": "erro", "motivo": f"Tipo de ação não suportado: {tipo}"}

                    erros_recentes.clear()
                    passos_aprendidos.append({"tipo": tipo, "seletor": seletor, "valor": valor})
                except Exception as exc:
                    msg_erro = (
                        f"Falha ao executar '{tipo}' no seletor '{seletor}'. "
                        f"Erro técnico: {str(exc)}"
                    )
                    if decisao_ia.seletor:
                        seletores_banidos.add(decisao_ia.seletor)
                    _LOGGER.warning(f"[AGENTE AUTO-CORREÇÃO] {msg_erro}")
                    erros_recentes.append(msg_erro)
                    erros_recentes = erros_recentes[-3:]
                    continue

            if not passos_aprendidos:
                return {"status": "erro", "motivo": "Nenhum passo executável foi aprendido durante o loop semântico."}

            # Trava de qualidade: evita gravar aprendizado sem ação concreta ou sem extração pedida.
            passos_concretos = [
                passo
                for passo in passos_aprendidos
                if isinstance(passo, dict)
                and str(passo.get("tipo", "")).lower() in {"clicar", "preencher", "teclar", "download_pdf"}
            ]
            instrucao_norm = str(instrucao_limpa or "").lower()
            exige_extracao = any(chave in instrucao_norm for chave in ["pegar", "extrair", "ler", "buscar", "baixar"])
            if not passos_concretos or (exige_extracao and not dados_extraidos):
                return {
                    "status": "erro",
                    "motivo": (
                        "O agente tentou navegar, mas não conseguiu realizar ações concretas ou não encontrou os "
                        "dados solicitados. A rotina não foi gravada para evitar falsos positivos."
                    ),
                }

            variaveis_necessarias: list[str] = []
            for i, mock_val in enumerate(variaveis_mock):
                var_key = f"var_{i + 1}"
                variaveis_necessarias.append(var_key)
                for passo in passos_aprendidos:
                    if passo.get("valor") == mock_val:
                        passo["variavel"] = var_key
                        passo["valor"] = ""

            await page.screenshot(path=str(screenshot_path), full_page=False)
            _LOGGER.info(f"[CARTÓGRAFO] Screenshot pós-aprendizado salvo em: {screenshot_path.name}")
    except Exception as exc:
        _LOGGER.info(f"[CARTÓGRAFO] Falha ao mapear ação '{nome_acao}': {exc}")
        _LOGGER.info("[ERRO] Obstáculo encontrado. Solicitando intervenção humana no chat.")
        return {"status": "erro", "motivo": f"Falha ao aceder ao sistema: {exc}"}
    finally:
        if browser is not None:
            await browser.close()

    return {
        "status": "sucesso",
        "passos_playwright": passos_aprendidos,
        "dados_extraidos": dados_extraidos,
        "variaveis_necessarias": variaveis_necessarias if "variaveis_necessarias" in locals() else [],
    }


async def executar_acao_rapida(
    nome_acao: str,
    passos_playwright: list,
    dados_variaveis: dict | None = None,
) -> dict:
    """
    Executa uma rotina aprendida sem uso de LLM (Fast-Track), repetindo os passos técnicos.
    """
    if not isinstance(passos_playwright, list) or not passos_playwright:
        return {"status": "erro", "motivo": "A rotina não possui passos para execução."}

    raiz = _raiz_projeto()
    url_sistema, usuario, senha = _carregar_erp_config()
    nome_arquivo = re.sub(r"[^\w\-]+", "_", str(nome_acao or "acao"), flags=re.UNICODE).strip("_")
    caminho_execucao = _DATA_DIR / f"execucao_{nome_arquivo}.png"
    caminho_evidencia_padrao = raiz / NOME_ARQUIVO_EVIDENCIA
    arquivos_baixados: list[str] = []
    dados_extraidos: dict[str, str] = {}

    browser: Browser | None = None
    _LOGGER.info(f"[FAST-TRACK] Iniciando execução rápida da ação: {nome_acao}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("ws://browserless:3000")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()

            try:
                login_ok, login_msg = await _login_automatico(page, url_sistema, usuario, senha)
            except Exception as exc:
                return {"status": "erro", "motivo": str(exc)}
            if not login_ok:
                return {"status": "erro", "motivo": login_msg}
            _LOGGER.info(f"[FAST-TRACK] {login_msg}")
            dados_variaveis = dados_variaveis if isinstance(dados_variaveis, dict) else {}
            for passo in passos_playwright:
                if not isinstance(passo, dict):
                    continue
                seletor = str(passo.get("seletor", "")).strip()
                tipo_acao = str(passo.get("tipo", "")).strip().lower()

                logging.info(f"[FAST-TRACK] Executando passo: {tipo_acao} em {seletor}")

                if tipo_acao in ["clicar", "preencher", "extrair_texto", "download_pdf"] and seletor:
                    try:
                        await page.locator(seletor).first.wait_for(state="visible", timeout=15000)
                    except Exception:
                        logging.debug(f"[FAST-TRACK] Timeout de visibilidade para {seletor}. Tentando fallback...")

                try:
                    if tipo_acao == "clicar":
                        elementos = page.locator(passo["seletor"])
                        quantidade = await elementos.count()
                        sucesso_clique = False

                        try:
                            async with page.expect_popup(timeout=3000) as popup_info:
                                for i in range(quantidade):
                                    if await elementos.nth(i).is_visible():
                                        await elementos.nth(i).click(timeout=5000)
                                        sucesso_clique = True
                                        break
                                if not sucesso_clique:
                                    await elementos.first.click(timeout=5000, force=True)

                            nova_aba = await popup_info.value
                            try:
                                await nova_aba.wait_for_load_state("networkidle", timeout=5000)
                            except Exception:
                                pass

                            page = nova_aba
                            logging.info(f"[NAVEGAÇÃO] Popup/Nova Aba detetada! Foco transferido para: {page.url}")

                        except Exception:
                            if not sucesso_clique:
                                try:
                                    await elementos.first.click(timeout=5000, force=True)
                                except Exception:
                                    pass

                            try:
                                await page.wait_for_load_state("networkidle", timeout=3000)
                            except Exception:
                                pass

                        await asyncio.sleep(2)

                    elif tipo_acao == "preencher":
                        if "variavel" in passo and dados_variaveis and str(passo["variavel"]) in dados_variaveis:
                            valor_final = str(dados_variaveis[str(passo["variavel"])])
                        else:
                            valor_final = str(passo.get("valor", ""))
                        elementos = page.locator(seletor)
                        quantidade = await elementos.count()
                        sucesso_preencher = False

                        for i in range(quantidade):
                            if await elementos.nth(i).is_visible():
                                await elementos.nth(i).fill(valor_final, timeout=5000)
                                sucesso_preencher = True
                                break

                        if not sucesso_preencher:
                            await elementos.first.fill(valor_final, timeout=5000, force=True)

                    elif tipo_acao == "teclar":
                        await page.keyboard.press(str(passo.get("valor", "")))
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            pass

                    elif tipo_acao == "extrair_texto":
                        elemento = page.locator(seletor).first
                        tag_name = await elemento.evaluate("el => el.tagName.toLowerCase()")

                        if tag_name in ["input", "textarea"]:
                            texto = await elemento.input_value(timeout=5000)
                            if not texto:
                                texto = await elemento.get_attribute("value", timeout=5000) or ""
                        else:
                            texto = await elemento.inner_text(timeout=5000)

                        dados_extraidos[seletor] = texto

                    elif tipo_acao == "download_pdf":
                        os.makedirs("downloads", exist_ok=True)
                        async with page.expect_download(timeout=60000) as download_info:
                            elementos = page.locator(seletor)
                            quantidade = await elementos.count()
                            sucesso_clique_dl = False

                            for i in range(quantidade):
                                if await elementos.nth(i).is_visible():
                                    await elementos.nth(i).click(timeout=5000)
                                    sucesso_clique_dl = True
                                    break

                            if not sucesso_clique_dl:
                                await elementos.first.click(timeout=5000, force=True)

                        download = await download_info.value
                        caminho_arquivo = f"downloads/{download.suggested_filename}"
                        await download.save_as(caminho_arquivo)
                        await _aguardar_arquivo_estavel(caminho_arquivo, timeout_segundos=45)
                        arquivos_baixados.append(caminho_arquivo)

                except Exception as e:
                    raise Exception(
                        f"Falha técnica no Fast-Track ao executar {tipo_acao} em {seletor}: {str(e)}"
                    ) from e

            await asyncio.sleep(1)
            await page.screenshot(path=str(caminho_execucao), full_page=False)
            await page.screenshot(path=str(caminho_evidencia_padrao), full_page=False)
            _LOGGER.info(f"[FAST-TRACK] Execução finalizada com evidência: {caminho_execucao.name}")
            return {
                "status": "sucesso",
                "evidencia": caminho_execucao.name,
                "arquivos_baixados": arquivos_baixados,
                "dados_extraidos": dados_extraidos,
            }
    except Exception as exc:
        _LOGGER.info(f"[ERRO] Falha na execução rápida '{nome_acao}': {exc}")
        return {"status": "erro", "motivo": f"Falha na execução rápida: {exc}"}
    finally:
        if browser is not None:
            await browser.close()
