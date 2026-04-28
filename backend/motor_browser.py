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
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
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


class PassoCartografo(BaseModel):
    tipo: str = Field(description="Tipo da ação, ex.: clicar")
    seletor: str = Field(description="Seletor CSS preciso do elemento")
    valor: str = Field(default="", description="Texto amigável do elemento escolhido")


def _carregar_erp_config() -> tuple[str, str, str]:
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
        await page.wait_for_navigation(wait_until="networkidle", timeout=15000)
    except Exception:
        _LOGGER.info("[LOGIN] Sem navegação explícita após clique; validando estado da tela.")

    url_inicial_norm = url_sistema.rstrip("/")
    url_atual_norm = page.url.rstrip("/")
    ainda_tem_senha = await page.locator("input[type='password'], #pass").count() > 0
    area_logada_detectada = (
        await page.locator(
            "nav, #menu, .menu, [id*='menu'], [class*='menu'], [data-testid*='menu'], [aria-label*='menu'], [id*='user'], [class*='user']"
        ).count()
        > 0
    )
    login_sucesso = (url_atual_norm != url_inicial_norm) or area_logada_detectada
    if (not login_sucesso) or ainda_tem_senha:
        msg = f"Login falhou ou página não redirecionou. URL atual: {page.url}"
        _LOGGER.info(f"[ERRO] {msg}")
        return False, msg

    _LOGGER.info("[LOGIN] Autenticação bem-sucedida.")
    return True, "Login concluído."


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
    url_sistema, usuario, senha = _carregar_erp_config()

    nome_arquivo = nome_acao.replace(" ", "_").replace("/", "_").replace("\\", "_")
    screenshot_path = raiz / f"mapeamento_{nome_arquivo}.png"

    browser: Browser | None = None
    _LOGGER.info(f"[CARTÓGRAFO] Acedendo a {url_sistema} para mapear a ação: {nome_acao}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("ws://browserless:3000")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            login_ok, login_msg = await _login_automatico(page, url_sistema, usuario, senha)
            if not login_ok:
                return {"status": "erro", "motivo": login_msg}
            _LOGGER.info(f"[LOGIN] {login_msg} Iniciando busca por: {instrucao_humana}")
            await page.screenshot(path=str(screenshot_path), full_page=False)
            _LOGGER.info(f"[CARTÓGRAFO] Screenshot pós-login salvo em: {screenshot_path.name}")

            _LOGGER.info("[CARTÓGRAFO] Extraindo mapa semântico do DOM interativo visível...")
            mapa_dom = await page.evaluate(
                """
                () => {
                  const interativos = Array.from(
                    document.querySelectorAll("button, a, input, [role='button'], [onclick], [tabindex]")
                  );
                  const visiveis = interativos.filter((el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return (
                      style &&
                      style.visibility !== "hidden" &&
                      style.display !== "none" &&
                      rect.width > 0 &&
                      rect.height > 0
                    );
                  });
                  return visiveis.slice(0, 100).map((el) => ({
                    tag: (el.tagName || "").toLowerCase(),
                    texto: (el.innerText || el.textContent || "").trim().slice(0, 120),
                    id: (el.id || "").trim(),
                    name: (el.getAttribute("name") || "").trim(),
                    href: (el.getAttribute("href") || "").trim()
                  }));
                }
                """
            )
            if not isinstance(mapa_dom, list) or not mapa_dom:
                return {"status": "erro", "motivo": "Nao consegui extrair elementos interativos da pagina atual."}
            mapa_dom = [item for item in mapa_dom if isinstance(item, dict) and (item.get("texto") or item.get("id") or item.get("name"))][:80]

            _LOGGER.info("[CARTÓGRAFO] Mapa do DOM extraído. Solicitando decisão semântica da IA...")
            llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0,
                api_key=os.getenv("OPENAI_API_KEY") or None,
            )
            llm_estruturado = llm.with_structured_output(PassoCartografo)
            prompt = (
                f"Instrução do Utilizador: '{instrucao_humana}'\n\n"
                f"Aqui está o mapa de elementos interativos da página atual: {json.dumps(mapa_dom, ensure_ascii=False)}\n\n"
                "Sua tarefa: Analisar a instrução e o mapa da página. Determine qual é o elemento exato "
                "que o utilizador quer interagir."
            )
            try:
                passo_ia = await llm_estruturado.ainvoke(prompt)
            except Exception as exc:
                return {"status": "erro", "motivo": f"Falha na análise semântica da IA: {exc}"}

            tipo_acao = str(getattr(passo_ia, "tipo", "clicar") or "clicar").strip().lower()
            seletor_ia = str(getattr(passo_ia, "seletor", "") or "").strip()
            valor_ia = str(getattr(passo_ia, "valor", "") or "").strip()
            if not seletor_ia:
                return {"status": "erro", "motivo": "A IA não retornou um seletor válido para execução."}

            _LOGGER.info(f"[IA SEMÂNTICA] Seletor escolhido pelo LLM: {seletor_ia}")
            _LOGGER.info(f"[CARTÓGRAFO] IA sugeriu seletor '{seletor_ia}' para a ação '{tipo_acao}'.")
            try:
                if tipo_acao == "clicar":
                    await page.click(seletor_ia)
                else:
                    return {"status": "erro", "motivo": f"Tipo de ação não suportado para execução: {tipo_acao}"}

                try:
                    await page.wait_for_load_state("networkidle", timeout=7000)
                except Exception:
                    await page.wait_for_timeout(2000)
                _LOGGER.info(f"[CARTÓGRAFO] Clique executado com sucesso no seletor IA: {seletor_ia}")
            except Exception as exc:
                _LOGGER.info(f"[ERRO] A IA analisou a tela, mas o seletor sugerido falhou. Seletor: {seletor_ia}")
                return {
                    "status": "erro",
                    "motivo": f"A IA analisou a tela, mas o seletor sugerido falhou. Detalhe técnico: {exc}",
                }

            passos_reais = [{"tipo": "clicar", "seletor": seletor_ia, "valor": valor_ia or seletor_ia}]
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


async def executar_acao_rapida(nome_acao: str, passos: list) -> dict:
    """
    Executa uma rotina aprendida sem uso de LLM (Fast-Track), repetindo os passos técnicos.
    """
    if not isinstance(passos, list) or not passos:
        return {"status": "erro", "motivo": "A rotina não possui passos para execução."}

    raiz = _raiz_projeto()
    url_sistema, usuario, senha = _carregar_erp_config()
    nome_arquivo = re.sub(r"[^\w\-]+", "_", str(nome_acao or "acao"), flags=re.UNICODE).strip("_")
    caminho_execucao = raiz / f"execucao_{nome_arquivo}.png"
    caminho_evidencia_padrao = raiz / NOME_ARQUIVO_EVIDENCIA

    browser: Browser | None = None
    _LOGGER.info(f"[FAST-TRACK] Iniciando execução rápida da ação: {nome_acao}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("ws://browserless:3000")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()

            login_ok, login_msg = await _login_automatico(page, url_sistema, usuario, senha)
            if not login_ok:
                return {"status": "erro", "motivo": login_msg}
            _LOGGER.info(f"[FAST-TRACK] {login_msg}")

            for idx, passo in enumerate(passos, start=1):
                if not isinstance(passo, dict):
                    continue
                tipo = str(passo.get("tipo", "")).lower()
                seletor = str(passo.get("seletor", "")).strip()
                if tipo != "clicar" or not seletor:
                    continue
                _LOGGER.info(f"[FAST-TRACK] Executando passo {idx}: clique em {seletor}")
                await page.click(seletor)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    await page.wait_for_timeout(1000)

            await page.screenshot(path=str(caminho_execucao), full_page=False)
            await page.screenshot(path=str(caminho_evidencia_padrao), full_page=False)
            _LOGGER.info(f"[FAST-TRACK] Execução finalizada com evidência: {caminho_execucao.name}")
            return {
                "status": "sucesso",
                "caminho_imagem": caminho_execucao.name,
                "caminho_evidencia_padrao": NOME_ARQUIVO_EVIDENCIA,
            }
    except Exception as exc:
        _LOGGER.info(f"[ERRO] Falha na execução rápida '{nome_acao}': {exc}")
        return {"status": "erro", "motivo": f"Falha na execução rápida: {exc}"}
    finally:
        if browser is not None:
            await browser.close()
