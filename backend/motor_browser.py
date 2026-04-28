"""
Motor físico de automação web: Playwright conectado ao Browserless via CDP.

O Browserless expõe um endpoint WebSocket para Chromium remoto; aqui usamos
`connect_over_cdp` para anexar uma sessão ao cluster sem gerenciar binários localmente.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
    """Acessa o ERP, tenta login automático e gera receita de mapeamento."""
    raiz = _raiz_projeto()
    erp_config_path = raiz / "erp_config.json"
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

    nome_arquivo = nome_acao.replace(" ", "_").replace("/", "_").replace("\\", "_")
    screenshot_path = raiz / f"mapeamento_{nome_arquivo}.png"
    passos_reais: list[dict[str, str]] = []

    # Parser simples de intenção para transformar frase em termos clicáveis.
    termos_brutos = re.split(r"\b(?:e depois|depois|então|entao|e)\b", instrucao_humana, flags=re.IGNORECASE)
    termos = [re.sub(r"[^a-zA-Z0-9À-ÿ_\- ]+", "", t).strip() for t in termos_brutos]
    termos = [t for t in termos if t]
    if not termos:
        return {"status": "erro", "motivo": "Nenhum passo identificável na instrução fornecida."}

    browser: Browser | None = None
    _LOGGER.info(f"[CARTÓGRAFO] Acedendo a {url_sistema} para mapear a ação: {nome_acao}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("ws://browserless:3000")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            _LOGGER.info("[LOGIN] Abrindo página inicial do ERP...")
            await page.goto(url_sistema, wait_until="networkidle")
            _LOGGER.info(f"[LOGIN] Página carregada em: {page.url}")

            has_password = await page.locator("input[type='password'], #pass").count() > 0
            has_login_field = (
                await page.locator(
                    "input[name='login'], input[name='username'], input[name='usuario'], #user"
                ).count()
                > 0
            )
            login_detectado = has_password or has_login_field
            if has_password or has_login_field:
                _LOGGER.info(
                    "[CARTÓGRAFO] Página de login detectada. Realizando login automático com credenciais configuradas..."
                )
                _LOGGER.info("[LOGIN] Tentando autenticação automática...")
                try:
                    usuario_sel = (
                        "#user, input[name='login'], input[name='username'], input[name='usuario'], "
                        "input[type='email'], input[type='text']"
                    )
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
                        _LOGGER.info("[ERRO] Botão de login não encontrado na página.")
                        return {
                            "status": "erro",
                            "motivo": "Botão de login não encontrado na página.",
                        }

                    _LOGGER.info(f"[LOGIN] Clicando em '{botao_login}' para autenticar.")
                    await page.click(botao_login)
                    try:
                        await page.wait_for_navigation(wait_until="networkidle", timeout=15000)
                    except Exception:
                        _LOGGER.info("[LOGIN] Sem navegação explícita após clique; validando estado da tela.")

                    url_inicial_norm = url_sistema.rstrip("/")
                    url_atual_norm = page.url.rstrip("/")
                    ainda_tem_senha = await page.locator("input[type='password'], #pass").count() > 0
                    area_logada_detectada = (
                        await page.locator(
                            "nav, #menu, .menu, [id*='menu'], [class*='menu'], "
                            "[data-testid*='menu'], [aria-label*='menu'], [id*='user'], [class*='user']"
                        ).count()
                        > 0
                    )
                    login_sucesso = (url_atual_norm != url_inicial_norm) or area_logada_detectada
                    if (not login_sucesso) or ainda_tem_senha:
                        _LOGGER.info(
                            f"[ERRO] Login falhou ou página não redirecionou. URL atual: {page.url}"
                        )
                        return {
                            "status": "erro",
                            "motivo": (
                                "Login falhou ou página não redirecionou; credenciais inválidas, "
                                "CAPTCHA ou fluxo desconhecido."
                            ),
                        }

                    _LOGGER.info(f"[LOGIN] Autenticação bem-sucedida. Iniciando busca por: {instrucao_humana}")
                except Exception as exc:
                    _LOGGER.info(f"[ERRO] Obstáculo encontrado. Solicitando intervenção humana no chat. ({exc})")
                    return {
                        "status": "erro",
                        "motivo": f"Falha no login automático: {exc}",
                    }

            # Só salva screenshot em cenário consistente: login bem-sucedido (quando havia login)
            # ou navegação sem tela de autenticação.
            if login_detectado:
                await page.screenshot(path=str(screenshot_path), full_page=False)
                _LOGGER.info(f"[CARTÓGRAFO] Screenshot pós-login salvo em: {screenshot_path.name}")
            else:
                await page.screenshot(path=str(screenshot_path), full_page=False)
                _LOGGER.info(f"[CARTÓGRAFO] Screenshot inicial salvo em: {screenshot_path.name}")

            for termo in termos:
                _LOGGER.info(f"[CARTÓGRAFO] Procurando elemento para termo: '{termo}'")
                alvo = None
                try:
                    by_text = page.get_by_text(termo, exact=False)
                    if await by_text.count() > 0:
                        alvo = by_text.first
                    else:
                        by_button = page.get_by_role("button", name=termo)
                        if await by_button.count() > 0:
                            alvo = by_button.first
                except Exception:
                    alvo = None

                if alvo is None:
                    _LOGGER.warning(f"[CARTÓGRAFO] Não consegui encontrar o botão '{termo}'.")
                    return {
                        "status": "erro",
                        "motivo": f"Nao consegui encontrar o elemento '{termo}' durante o aprendizado.",
                    }

                try:
                    await alvo.click()
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        await page.wait_for_timeout(2000)
                    passo = {"tipo": "clicar", "seletor": f"text={termo}", "valor": termo}
                    passos_reais.append(passo)
                    _LOGGER.info(f"[CARTÓGRAFO] Elemento '{termo}' encontrado e clicado.")
                except Exception as exc:
                    _LOGGER.warning(f"[CARTÓGRAFO] Falha ao clicar em '{termo}': {exc}")
                    return {
                        "status": "erro",
                        "motivo": f"Elemento '{termo}' encontrado, mas o clique falhou: {exc}",
                    }
    except Exception as exc:
        _LOGGER.info(f"[CARTÓGRAFO] Falha ao mapear ação '{nome_acao}': {exc}")
        _LOGGER.info("[ERRO] Obstáculo encontrado. Solicitando intervenção humana no chat.")
        return {
            "status": "erro",
            "motivo": f"Falha ao aceder ao sistema: {exc}",
        }
    finally:
        if browser is not None:
            await browser.close()

    # Gera uma "receita" no padrão estrito da arquitetura com um nome curto e claro
    nome_curto = nome_acao.replace("_", " ").title()
    passos_aprendidos = {
        "nome_amigavel": nome_curto,
        "descricao": f"Ação aprendida: {instrucao_humana[:30]}...",
        "url_inicial": "Lida do erp_config.json",
        "passos_playwright": passos_reais,
    }
    return {
        "status": "sucesso",
        "passos_aprendidos": passos_aprendidos,
    }
