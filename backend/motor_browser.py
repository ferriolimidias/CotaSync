"""
Motor físico de automação web: Playwright conectado ao Browserless via CDP.

O Browserless expõe um endpoint WebSocket para Chromium remoto; aqui usamos
`connect_over_cdp` para anexar uma sessão ao cluster sem gerenciar binários localmente.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import Browser, async_playwright

load_dotenv()

# Nome do ficheiro de evidência na raiz do projeto (alinhado ao Streamlit e à tool do agente).
NOME_ARQUIVO_EVIDENCIA = "print_teste.png"
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


async def consultar_erp_real(cnpj: str) -> dict[str, Any]:
    """
    Navegação real de validação: Wikipedia PT + busca + screenshot na raiz do projeto.

    Nota: o parâmetro é tratado como texto de busca (ex.: CNPJ) para o campo da wiki.
    """
    raiz = _raiz_projeto()
    caminho_imagem = raiz / NOME_ARQUIVO_EVIDENCIA
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
                    "caminho_imagem": NOME_ARQUIVO_EVIDENCIA,
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


async def acionar_ia_cartografa(nome_acao: str, instrucao_humana: str) -> dict:
    """Simula a IA acessando o ERP e descobrindo os botões baseada na instrução humana."""
    raiz = _raiz_projeto()
    erp_config_path = raiz / "erp_config.json"
    url_sistema = "https://google.com"
    try:
        if erp_config_path.is_file():
            config = json.loads(erp_config_path.read_text(encoding="utf-8"))
            if isinstance(config, dict):
                url_sistema = str(config.get("url_sistema") or url_sistema).strip() or url_sistema
    except (json.JSONDecodeError, OSError):
        pass

    nome_arquivo = nome_acao.replace(" ", "_").replace("/", "_").replace("\\", "_")
    screenshot_path = raiz / f"mapeamento_{nome_arquivo}.png"

    browser: Browser | None = None
    _LOGGER.info(f"[CARTÓGRAFO] Acedendo a {url_sistema} para mapear a ação: {nome_acao}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("ws://browserless:3000")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            await page.goto(url_sistema, wait_until="networkidle")
            await page.screenshot(path=str(screenshot_path), full_page=False)
            _LOGGER.info(f"[CARTÓGRAFO] Screenshot inicial salvo em: {screenshot_path.name}")
    except Exception as exc:
        _LOGGER.info(f"[CARTÓGRAFO] Falha ao mapear ação '{nome_acao}': {exc}")
    finally:
        if browser is not None:
            await browser.close()

    # Gera uma "receita" no padrão estrito da arquitetura com um nome curto e claro
    nome_curto = nome_acao.replace("_", " ").title()
    passos_aprendidos = {
        "nome_amigavel": nome_curto,
        "descricao": f"Ação aprendida: {instrucao_humana[:30]}...",
        "url_inicial": "Lida do erp_config.json",
        "passos_playwright": [
            {"tipo": "preencher", "seletor": "#campo_busca_simulado", "variavel": "input_usuario"},
            {"tipo": "clicar", "seletor": "#btn_confirmar_simulado"},
        ],
    }
    return passos_aprendidos
