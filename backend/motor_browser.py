"""
Motor físico de automação web: Playwright conectado ao Browserless via CDP.

O Browserless expõe um endpoint WebSocket para Chromium remoto; aqui usamos
`connect_over_cdp` para anexar uma sessão ao cluster sem gerenciar binários localmente.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import Browser, async_playwright

load_dotenv()


async def obter_browser_browserless() -> tuple[Any, Browser]:
    """
    Inicia o Playwright e conecta ao Chromium remoto (Browserless).

    Returns:
        Tupla (playwright_instance, browser) para que o chamador possa fazer
        `await playwright.stop()` após uso, se necessário.
    """
    ws_url = os.getenv("BROWSERLESS_URL", "ws://localhost:3000").strip()
    if not ws_url.startswith("ws"):
        # Alguns deployments usam http; Browserless costuma aceitar ws explícito.
        ws_url = ws_url.replace("http://", "ws://").replace("https://", "wss://")

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
