"""Motor físico de automação web via Playwright/CDP no Desktop Browser persistente."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
import pandas as pd
from pydantic import BaseModel, Field
from playwright.async_api import Browser, async_playwright
import requests

from backend.services.action_pages import (
    ActionPageError,
    select_desktop_page_for_action,
    url_host,
    validate_action_page_url,
)
from backend.services.browser_providers import browser_provider, normalize_browser_mode
from backend.services.client_fields import canonical_client_field_key
from backend.services.extraction_targets import extract_value_near_label
from backend.services.file_names import safe_file_name
from backend.services.result_selection import extraction_contract_from_action, extract_with_contract
from backend.services.runtime_files import runtime_download_path, runtime_file_metadata
from backend.services.session_guardian import SessionGuardian, SessionGuardianError, session_failure_message

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


def _safe_result_url(url: str) -> str:
    """Remove credenciais, query e fragmento antes de persistir a pagina final."""
    try:
        parsed = urlsplit(str(url or ""))
        hostname = parsed.hostname or ""
        if parsed.port:
            hostname = f"{hostname}:{parsed.port}"
        return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))
    except Exception:
        return ""


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


def _arquivo_pdf_valido(caminho_pdf: str) -> bool:
    """Validação imediata: existência, tamanho mínimo e assinatura PDF."""
    if not os.path.exists(caminho_pdf):
        return False
    tamanho = os.path.getsize(caminho_pdf)
    if tamanho <= 1024:
        return False
    try:
        with open(caminho_pdf, "rb") as f:
            assinatura = f.read(5)
        return assinatura == b"%PDF-"
    except OSError:
        return False


async def _extrator_universal_de_download(page: Any, botao_locator: str, caminho_destino: str) -> bool:
    """
    Estratégia tripla para download robusto:
    1) save_as nativo com validação imediata.
    2) GET autenticado via Python com cookies/sessão.
    3) Fallback blob/base64 via page.evaluate.
    """
    os.makedirs(str(Path(caminho_destino).parent), exist_ok=True)
    download_url = ""

    # Camada 1: stream nativo do Playwright
    try:
        logging.info("[DOWNLOAD] Camada 1: aguardando evento nativo de download...")
        async with page.expect_download(timeout=60000) as download_info:
            elementos = page.locator(botao_locator)
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
        download_url = str(getattr(download, "url", "") or "")
        logging.info(
            "[DOWNLOAD] Evento capturado. Origem detectada: %s",
            _safe_result_url(download_url) if download_url else "N/A",
        )
        await download.save_as(caminho_destino)
        await asyncio.sleep(2)  # Garantia extra de flush no disco após save_as
        if _arquivo_pdf_valido(caminho_destino):
            logging.info(f"[DOWNLOAD] Camada 1 concluída com sucesso: {caminho_destino}")
            return True
        logging.warning("[DOWNLOAD] Camada 1 falhou na validação imediata. Avançando fallback...")
    except Exception as exc:
        logging.warning(f"[DOWNLOAD] Camada 1 falhou: {exc}")

    # Camada 2: requisição autenticada no Python (se URL não blob)
    if download_url and not download_url.startswith("blob:"):
        try:
            logging.info("[DOWNLOAD] Camada 2: tentativa via requisição autenticada Python...")
            cookies = await page.context.cookies()
            cookies_dict = {str(c.get("name", "")): str(c.get("value", "")) for c in cookies if c.get("name")}
            user_agent = await page.evaluate("() => navigator.userAgent")
            headers = {
                "User-Agent": str(user_agent or ""),
                "Accept": "application/pdf,application/octet-stream,*/*",
            }

            def _baixar_sync() -> None:
                resp = requests.get(download_url, headers=headers, cookies=cookies_dict, timeout=60)
                resp.raise_for_status()
                with open(caminho_destino, "wb") as f:
                    f.write(resp.content)

            await asyncio.to_thread(_baixar_sync)
            if _arquivo_pdf_valido(caminho_destino):
                logging.info(f"[DOWNLOAD] Camada 2 concluída com sucesso: {caminho_destino}")
                return True
            logging.warning("[DOWNLOAD] Camada 2 falhou na validação. Avançando fallback blob...")
        except Exception as exc:
            logging.warning(f"[DOWNLOAD] Camada 2 falhou: {exc}")

    # Camada 3: blob -> base64 no browser -> bytes no Python
    if download_url.startswith("blob:"):
        try:
            logging.info("[DOWNLOAD] Camada 3: fallback blob/base64...")
            conteudo_b64 = await page.evaluate(
                """
                async (blobUrl) => {
                    const response = await fetch(blobUrl);
                    const blob = await response.blob();
                    return await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onloadend = () => {
                            const dataUrl = String(reader.result || "");
                            const idx = dataUrl.indexOf(",");
                            resolve(idx >= 0 ? dataUrl.slice(idx + 1) : "");
                        };
                        reader.onerror = () => reject(new Error("Falha no FileReader"));
                        reader.readAsDataURL(blob);
                    });
                }
                """,
                download_url,
            )
            if not conteudo_b64:
                raise RuntimeError("Base64 vazio retornado do blob")
            binario = base64.b64decode(str(conteudo_b64))
            with open(caminho_destino, "wb") as f:
                f.write(binario)
            if _arquivo_pdf_valido(caminho_destino):
                logging.info(f"[DOWNLOAD] Camada 3 concluída com sucesso: {caminho_destino}")
                return True
        except Exception as exc:
            logging.warning(f"[DOWNLOAD] Camada 3 falhou: {exc}")

    raise RuntimeError(f"Falha ao obter PDF íntegro após todas as camadas: {caminho_destino}")


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


async def consultar_erp_real(cnpj: str) -> dict[str, Any]:
    """
    Navegação real de validação: Wikipedia PT + busca + screenshot na raiz do projeto.

    Nota: o parâmetro é tratado como texto de busca (ex.: CNPJ) para o campo da wiki.
    """
    raiz = _raiz_projeto()
    caminho_imagem = _DATA_DIR / "print_teste.png"
    browser: Browser | None = None

    try:
        async with async_playwright() as p:
            connection = await browser_provider("desktop_browser").connect(p, "consulta-erp-real")
            browser = connection.browser
            try:
                context = connection.context
                page = connection.page if not connection.page.is_closed() else await context.new_page()
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


async def exemplo_navegacao(url: str = "https://example.com") -> str:
    """Exemplo mínimo: abre uma página no Desktop Browser e retorna o título."""
    pw = await async_playwright().start()
    connection = await browser_provider("desktop_browser").connect(pw, "exemplo-navegacao")
    browser = connection.browser
    try:
        context = connection.context
        page = connection.page if not connection.page.is_closed() else await context.new_page()
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
    nome_arquivo = safe_file_name(nome_acao)
    screenshot_path = _DATA_DIR / f"mapeamento_{nome_arquivo}.png"
    passos_aprendidos: list[dict[str, str]] = []
    dados_extraidos: dict[str, str] = {}
    erros_recentes: list[str] = []
    seletores_banidos: set[str] = set()

    browser: Browser | None = None
    _LOGGER.info(f"[CARTÓGRAFO] Acedendo a {url_sistema} para mapear a ação: {nome_acao}")
    try:
        async with async_playwright() as p:
            connection = await browser_provider("desktop_browser").connect(p, f"learn-{nome_arquivo}")
            browser = connection.browser
            context = connection.context
            page = connection.page if not connection.page.is_closed() else await context.new_page()
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
                        caminho_arquivo = downloads_dir / f"{nome_arquivo}.pdf"
                        await _extrator_universal_de_download(page, seletor, str(caminho_arquivo))
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


async def verify_postcondition(page: Any, selector: str, step_index: int, *, timeout_ms: int = 15000) -> None:
    expected_selector = str(selector or "").strip()
    if not expected_selector:
        return
    try:
        await page.locator(expected_selector).first.wait_for(state="visible", timeout=timeout_ms)
    except Exception as exc:
        raise RuntimeError(
            f"Pós-condição não alcançada após o passo {step_index}: {expected_selector}"
        ) from exc


async def verify_query_result_refresh(
    page: Any,
    selector: str,
    step_index: int,
    *,
    before_url: str,
    before_html: str,
    navigation_observed: bool,
    timeout_ms: int = 15000,
) -> None:
    """Confirma que o resultado pertence a uma atualização posterior ao submit."""
    expected_selector = str(selector or "").strip()
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        try:
            locator = page.locator(expected_selector).first
            if await locator.count() > 0 and await locator.is_visible():
                current_url = _safe_result_url(str(getattr(page, "url", "") or ""))
                current_html = ""
                try:
                    current_html = str(await locator.evaluate("element => element.outerHTML"))
                except Exception:
                    pass
                if navigation_observed or current_url != before_url or not before_html or current_html != before_html:
                    return
        except Exception:
            pass
        await asyncio.sleep(0.1)
    raise RuntimeError(
        f"Resultado da consulta não foi confirmado após o passo {step_index}: {expected_selector}"
    )


def query_result_matches_inputs(page_text: str, variables: dict[str, Any]) -> bool:
    """Valida a identificação textual da consulta sem exigir que o resultado numérico mude."""
    group = re.sub(r"\D", "", str(variables.get("grupo") or ""))
    quota = re.sub(r"\D", "", str(variables.get("cota") or ""))
    version = re.sub(r"\D", "", str(variables.get("versao") or ""))
    if not group or not quota or not version:
        return True
    compact = " ".join(str(page_text or "").split())
    pattern = rf"0*{re.escape(group)}\s+0*{re.escape(quota)}[-/]0*{re.escape(version)}(?:\D|$)"
    return re.search(pattern, compact) is not None


async def executar_acao_rapida(
    nome_acao: str,
    passos_playwright: list,
    dados_variaveis: dict | None = None,
    action_config: dict[str, Any] | None = None,
    run_id: str = "",
) -> dict:
    """
    Executa uma rotina aprendida sem uso de LLM (Desktop replay), repetindo os passos técnicos.
    """
    if not isinstance(passos_playwright, list) or not passos_playwright:
        return {"status": "erro", "motivo": "A rotina não possui passos para execução."}

    raiz = _raiz_projeto()
    url_sistema, usuario, senha = _carregar_erp_config()
    nome_arquivo = safe_file_name(nome_acao)
    caminho_execucao = _DATA_DIR / f"execucao_{nome_arquivo}.png"
    caminho_evidencia_padrao = raiz / NOME_ARQUIVO_EVIDENCIA
    arquivos_baixados: list[str] = []
    downloaded_files: list[dict[str, object]] = []
    dados_extraidos: dict[str, str] = {}
    step_trace: list[dict[str, Any]] = []
    last_successful_step_index: int | str = ""
    page: Any | None = None

    async def current_browser_state(page_to_check: Any | None) -> dict[str, str]:
        if page_to_check is None:
            return {"current_url": "", "current_host": "", "page_title": ""}
        current_url = _safe_result_url(str(getattr(page_to_check, "url", "") or ""))
        page_title = ""
        try:
            page_title = (await page_to_check.title()).strip()[:200]
        except Exception:
            page_title = ""
        return {
            "current_url": current_url,
            "current_host": url_host(current_url),
            "page_title": page_title,
        }

    action_config = action_config if isinstance(action_config, dict) else {}
    browser_mode = normalize_browser_mode(action_config.get("browser_mode") or "desktop_browser")
    provider = browser_provider(browser_mode)
    browser: Browser | None = None
    _LOGGER.info(f"[DESKTOP-REPLAY] Iniciando execução rápida da ação: {nome_acao}")
    try:
        async with async_playwright() as p:
            guardian = SessionGuardian()
            recovery_attempted = False
            total_recovery_attempts = 0
            recovery_steps: list[dict[str, Any]] = []
            checkpoint_diagnostics: list[dict[str, Any]] = []
            last_session_state = ""
            last_page_title = ""
            current_host = ""

            async def capture_error_screenshot(page_to_capture: Any | None, step_index: int, step_type: str) -> str:
                if page_to_capture is None:
                    return ""
                try:
                    evidence_path = _DATA_DIR / "runs" / f"{run_id}_step_{step_index}_{safe_file_name(step_type)}_error.png"
                    evidence_path.parent.mkdir(parents=True, exist_ok=True)
                    await page_to_capture.screenshot(path=str(evidence_path), full_page=False, timeout=15000)
                    return str(evidence_path.relative_to(_raiz_projeto()))
                except Exception as exc:
                    _LOGGER.warning(
                        "[DESKTOP-REPLAY] Falha ao salvar screenshot de erro no passo %s: %s",
                        step_index,
                        type(exc).__name__,
                    )
                    return ""

            async def build_step_failure_diagnostics(
                page_to_check: Any | None,
                step_index: int,
                passo: dict[str, Any],
                exc: Exception,
                *,
                screenshot_path: str = "",
            ) -> dict[str, Any]:
                state = await current_browser_state(page_to_check)
                selector = str(passo.get("seletor") or "").strip()
                diagnostics: dict[str, Any] = {
                    "step_index": step_index,
                    "step_type": str(passo.get("tipo") or "").strip().lower(),
                    "step_selector": selector,
                    "selector": selector,
                    "step_value_template": str(passo.get("valor") or ""),
                    "step_variable_key": str(passo.get("variavel") or ""),
                    "current_url": state["current_url"],
                    "current_host": state["current_host"],
                    "page_title": state["page_title"],
                    "last_page_title": state["page_title"],
                    "screenshot_path": screenshot_path,
                    "reason": str(exc)[:1000] or type(exc).__name__,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc)[:1000] or type(exc).__name__,
                    "browser_mode": browser_mode,
                    "runner": "desktop_browser_replay",
                    "whether_desktop_browser_used": True,
                    "last_successful_step_index": last_successful_step_index,
                    "next_step_expected_selector": str(passo.get("expected_selector_after") or ""),
                    "next_step_expected_text": str(passo.get("target_text") or passo.get("target_label") or ""),
                    "input_variables": dados_variaveis if isinstance(dados_variaveis, dict) else {},
                    "step_trace": step_trace,
                    "session_state": last_session_state,
                    "current_host_from_guardian": current_host,
                    "checkpoint_diagnostics": checkpoint_diagnostics,
                    "retryable": True,
                }
                try:
                    if selector and page_to_check is not None:
                        locator = page_to_check.locator(selector)
                        count = await locator.count()
                        diagnostics["count"] = count
                        diagnostics["visible"] = await locator.first.is_visible() if count else False
                        diagnostics["enabled"] = await locator.first.is_enabled() if count else False
                except Exception:
                    pass
                return diagnostics

            async def is_authenticated(page_to_check: Any) -> bool:
                try:
                    validate_action_page_url(action_config, getattr(page_to_check, "url", ""))
                    return True
                except ActionPageError as e:
                    return False

            async def run_session_checkpoint(
                page_to_check: Any,
                checkpoint: str,
                next_step: dict[str, Any] | None = None,
            ) -> None:
                nonlocal recovery_attempted
                nonlocal total_recovery_attempts
                nonlocal recovery_steps
                nonlocal last_session_state
                nonlocal last_page_title
                nonlocal current_host
                if (
                    guardian is None
                    or not bool(action_config.get("requires_authenticated_session", True))
                    or not bool(action_config.get("session_guardian_enabled", True))
                ):
                    return
                started_at = time.monotonic()
                authenticated = await is_authenticated(page_to_check)
                state = await guardian.classify(
                    page_to_check,
                    action_config,
                    authenticated=authenticated,
                )
                if state.state == "authenticated_system":
                    last_session_state = state.state
                    last_page_title = state.title
                    current_host = state.current_host
                    checkpoint_diagnostics.append(
                        {
                            "checkpoint": checkpoint,
                            "session_state": state.state,
                            "elapsed_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                            "recovery_attempted": False,
                            "recovery_attempts": 0,
                            "result": "success",
                            "current_host": state.current_host,
                            "last_page_title": state.title,
                        }
                    )
                    return
                learned_step_diagnostic = await guardian.learned_microsoft_step_diagnostic(
                    page_to_check,
                    action_config,
                    next_step,
                    state=state,
                    authenticated=authenticated,
                )
                if learned_step_diagnostic.get("learned_microsoft_step_compatible") is True:
                    last_session_state = state.state
                    last_page_title = state.title
                    current_host = state.current_host
                    checkpoint_diagnostics.append(
                        {
                            "checkpoint": checkpoint,
                            "session_state": state.state,
                            "elapsed_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                            "recovery_attempted": False,
                            "recovery_attempts": 0,
                            "result": "learned_microsoft_step_allowed",
                            "current_host": state.current_host,
                            "last_page_title": state.title,
                            "next_step_index": learned_step_diagnostic.get("next_step_index"),
                            "next_step_type": learned_step_diagnostic.get("next_step_type"),
                            "next_step_selector": learned_step_diagnostic.get("next_step_selector"),
                            "next_step_url_before": learned_step_diagnostic.get("next_step_url_before"),
                            "next_step_host_before": learned_step_diagnostic.get("next_step_host_before"),
                            "next_step_expected_selector": learned_step_diagnostic.get("next_step_expected_selector"),
                            "next_step_expected_url_or_host": learned_step_diagnostic.get(
                                "next_step_expected_url_or_host"
                            ),
                            "next_step_expected_text": learned_step_diagnostic.get("next_step_expected_text"),
                            "whether_next_step_was_microsoft_click": learned_step_diagnostic.get(
                                "whether_next_step_was_microsoft_click"
                            ),
                            "learned_microsoft_step_compatible": learned_step_diagnostic.get(
                                "learned_microsoft_step_compatible"
                            ),
                            "matched_by": learned_step_diagnostic.get("matched_by"),
                        }
                    )
                    return
                if state.state.startswith("microsoft_") or state.state == "unknown_microsoft_auth":
                    last_session_state = state.state
                    last_page_title = state.title
                    current_host = state.current_host
                    learned_step_diagnostic["checkpoint_diagnostics"] = checkpoint_diagnostics + [
                        {
                            "checkpoint": checkpoint,
                            "session_state": state.state,
                            "elapsed_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                            "recovery_attempted": False,
                            "recovery_attempts": 0,
                            "result": "failed",
                            "current_host": state.current_host,
                            "last_page_title": state.title,
                            "reason": learned_step_diagnostic.get("reason"),
                            "next_step_index": learned_step_diagnostic.get("next_step_index"),
                            "next_step_type": learned_step_diagnostic.get("next_step_type"),
                            "next_step_selector": learned_step_diagnostic.get("next_step_selector"),
                            "next_step_url_before": learned_step_diagnostic.get("next_step_url_before"),
                            "next_step_host_before": learned_step_diagnostic.get("next_step_host_before"),
                            "next_step_expected_selector": learned_step_diagnostic.get("next_step_expected_selector"),
                            "next_step_expected_url_or_host": learned_step_diagnostic.get(
                                "next_step_expected_url_or_host"
                            ),
                            "next_step_expected_text": learned_step_diagnostic.get("next_step_expected_text"),
                            "whether_next_step_was_microsoft_click": learned_step_diagnostic.get(
                                "whether_next_step_was_microsoft_click"
                            ),
                        }
                    ]
                    raise SessionGuardianError(
                        session_failure_message(state.state, str(learned_step_diagnostic.get("reason") or state.reason)),
                        learned_step_diagnostic,
                    )
                result = await guardian.ensure_authenticated(
                    page_to_check,
                    action_config,
                    is_authenticated=lambda _page: asyncio.sleep(0, result=authenticated),
                    checkpoint=checkpoint,
                )
                last_session_state = result.state.state
                last_page_title = result.state.title
                current_host = result.state.current_host
                total_recovery_attempts += result.recovery_attempts
                recovery_attempted = recovery_attempted or result.recovery_attempted
                recovery_steps.extend(result.recovery_steps)
                checkpoint_diagnostics.append(
                    {
                        "checkpoint": checkpoint,
                        "session_state": result.state.state,
                        "elapsed_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                        "recovery_attempted": result.recovery_attempted,
                        "recovery_attempts": result.recovery_attempts,
                        "result": "success" if result.ok else "failed",
                        "current_host": result.state.current_host,
                        "last_page_title": result.state.title,
                    }
                )
                if not result.ok:
                    diagnostics = result.diagnostics()
                    diagnostics["checkpoint_diagnostics"] = checkpoint_diagnostics
                    raise SessionGuardianError(
                        session_failure_message(result.state.state, result.state.reason),
                        diagnostics,
                    )

            async def validate_or_allow_learned_microsoft_step(
                page_to_check: Any,
                next_step: dict[str, Any] | None,
                checkpoint: str,
            ) -> None:
                try:
                    validate_action_page_url(action_config, page_to_check.url)
                    await run_session_checkpoint(page_to_check, checkpoint, next_step)
                    return
                except ActionPageError as e:
                    await run_session_checkpoint(page_to_check, checkpoint, next_step)

            async def learned_click_locator(page_to_click: Any, step: dict[str, Any]) -> Any:
                selector = str(step.get("seletor") or "").strip()
                if selector:
                    elementos = page_to_click.locator(selector)
                    try:
                        if await elementos.count() > 0:
                            return elementos
                    except Exception:
                        pass
                for key in ("target_text", "target_label"):
                    text = str(step.get(key) or "").strip()
                    if not text:
                        continue
                    for method_name in ("get_by_text", "get_by_label"):
                        method = getattr(page_to_click, method_name, None)
                        if method is None:
                            continue
                        try:
                            elementos = method(text, exact=False)
                            if await elementos.count() > 0:
                                return elementos
                        except Exception:
                            continue
                return page_to_click.locator(selector)

            async def apply_reviewed_overlay_waits(page_to_wait: Any, step_index: int) -> list[dict[str, Any]]:
                overlay = action_config.get("reviewed_overlay") if isinstance(action_config, dict) else {}
                if not isinstance(overlay, dict):
                    return []
                raw_waits = overlay.get("waits") or overlay.get("wait_suggestions") or []
                if not isinstance(raw_waits, list):
                    return []
                applied: list[dict[str, Any]] = []
                for raw_wait in raw_waits:
                    if not isinstance(raw_wait, dict):
                        continue
                    try:
                        after_index = int(raw_wait.get("after_step_index"))
                    except (TypeError, ValueError):
                        continue
                    if after_index != step_index:
                        continue
                    strategy = str(raw_wait.get("strategy") or raw_wait.get("type") or "").strip().lower()
                    target = str(raw_wait.get("target") or raw_wait.get("selector") or raw_wait.get("text") or "").strip()
                    started = time.monotonic()
                    status = "success"
                    try:
                        if strategy in {"wait_for_text", "text"} and target:
                            await page_to_wait.get_by_text(target, exact=False).first.wait_for(
                                state="visible",
                                timeout=15000,
                            )
                        elif strategy in {"wait_for_selector", "selector"} and target:
                            await page_to_wait.locator(target).first.wait_for(state="visible", timeout=15000)
                        elif strategy in {"networkidle", "load_state"}:
                            await page_to_wait.wait_for_load_state("networkidle", timeout=15000)
                        elif strategy in {"delay", "sleep"}:
                            await asyncio.sleep(min(5.0, max(0.1, float(raw_wait.get("seconds") or 1))))
                        else:
                            continue
                    except Exception as exc:
                        status = "timeout"
                        applied.append(
                            {
                                "after_step_index": step_index,
                                "strategy": strategy,
                                "target": target,
                                "status": status,
                                "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
                                "reason": str(exc)[:300],
                            }
                        )
                        continue
                    applied.append(
                        {
                            "after_step_index": step_index,
                            "strategy": strategy,
                            "target": target,
                            "status": status,
                            "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
                        }
                    )
                return applied

            def step_for_diagnostic(step: dict[str, Any] | None, index: int | None) -> dict[str, Any] | None:
                if not isinstance(step, dict):
                    return None
                enriched = dict(step)
                if index is not None:
                    enriched["__cotasync_step_index"] = index
                return enriched

            connection = await provider.connect(p, f"action-{nome_arquivo}")
            browser = connection.browser
            context = connection.context
            try:
                page = await select_desktop_page_for_action(action_config, context, connection.page)
            except ActionPageError as exc:
                if getattr(exc, "diagnostics", {}).get("reason") != "reauthentication_required":
                    raise
                page = connection.page
            first_step = step_for_diagnostic(
                passos_playwright[0] if passos_playwright and isinstance(passos_playwright[0], dict) else None,
                0,
            )
            observation = await guardian.observe_workflow_state(
                page,
                action_config,
                authenticated=await is_authenticated(page),
            )
            workflow_state = str(observation.get("workflow_state") or "unknown")
            if workflow_state == "auth_continue":
                initial_plan = await guardian.plan_resume_index(page, action_config, observation)
            elif workflow_state in {"auth_secret_required", "microsoft_password_required", "microsoft_mfa_required"} or workflow_state.startswith("microsoft_"):
                await run_session_checkpoint(page, "before_action_auth_check", first_step)
                initial_plan = {"resume_index": None, "reason": workflow_state}
            else:
                initial_plan = await guardian.plan_resume_index(page, action_config, observation)
            stateful_replay = bool(observation.get("stateful", True))
            last_session_state = workflow_state
            initial_evidence = observation.get("evidence") or {}
            last_page_title = str(initial_evidence.get("title") or "")
            current_host = str(initial_evidence.get("current_host") or "")
            if initial_plan.get("resume_index") is None and stateful_replay:
                diagnostics = dict(observation.get("evidence") or {})
                diagnostics.update(
                    {
                        "reason": initial_plan.get("reason") or "unknown_browser_state",
                        "workflow_state": workflow_state,
                        "operator_action_required": workflow_state in {"auth_secret_required", "unknown"},
                        "retryable": workflow_state == "unknown",
                    }
                )
                raise SessionGuardianError(
                    "Não foi possível determinar com segurança a próxima etapa do navegador.",
                    diagnostics,
                )
            resume_index = int(initial_plan.get("resume_index") or 0)
            skipped_steps = list(range(resume_index))
            checkpoint_diagnostics.append(
                {
                    "checkpoint": "workflow_observation",
                    "workflow_state": workflow_state,
                    "resume_index": resume_index,
                    "skipped_steps": skipped_steps,
                    "reentry_strategy": initial_plan.get("reentry_strategy", ""),
                    "target_workflow_state": initial_plan.get("target_workflow_state", ""),
                    "current_host": observation.get("evidence", {}).get("current_host", ""),
                    "current_url": observation.get("evidence", {}).get("current_url", ""),
                    "result": "planned",
                }
            )
            _LOGGER.info("[DESKTOP-REPLAY] Pagina desktop do sistema alvo selecionada.")
            dados_variaveis = dados_variaveis if isinstance(dados_variaveis, dict) else {}
            contract_for_query = extraction_contract_from_action(action_config if isinstance(action_config, dict) else {})
            selector_data_for_query = contract_for_query.get("selector_data") if isinstance(contract_for_query, dict) else {}
            result_selector_for_query = str(selector_data_for_query.get("primary") or "").strip() if isinstance(selector_data_for_query, dict) else ""
            for step_index, passo in enumerate(passos_playwright):
                if not isinstance(passo, dict):
                    continue
                if step_index < resume_index:
                    continue
                next_step = (
                    passos_playwright[step_index + 1]
                    if step_index + 1 < len(passos_playwright) and isinstance(passos_playwright[step_index + 1], dict)
                    else None
                )
                current_step_diagnostic = step_for_diagnostic(passo, step_index)
                next_step_diagnostic = step_for_diagnostic(next_step, step_index + 1 if next_step is not None else None)
                seletor = str(passo.get("seletor", "")).strip()
                tipo_acao = str(passo.get("tipo", "")).strip().lower()
                step_started_at = time.monotonic()
                is_query_submit = bool(
                    result_selector_for_query
                    and tipo_acao == "clicar"
                    and not any(
                        str(later.get("tipo") or later.get("type") or "").strip().lower() in {"clicar", "preencher"}
                        for later in passos_playwright[step_index + 1 :]
                        if isinstance(later, dict)
                    )
                )
                query_before_url = _safe_result_url(str(getattr(page, "url", "") or "")) if is_query_submit else ""
                query_before_html = ""
                if is_query_submit:
                    try:
                        result_locator_before = page.locator(result_selector_for_query).first
                        if await result_locator_before.count() > 0:
                            query_before_html = str(await result_locator_before.evaluate("element => element.outerHTML"))
                    except Exception:
                        query_before_html = ""
                navigation_observed = False

                def observe_main_frame_navigation(frame: Any) -> None:
                    nonlocal navigation_observed
                    if frame == getattr(page, "main_frame", None):
                        navigation_observed = True

                if is_query_submit:
                    try:
                        page.on("framenavigated", observe_main_frame_navigation)
                    except Exception:
                        pass
                before_state = await current_browser_state(page)
                trace_item: dict[str, Any] = {
                    "step_index": step_index,
                    "step_type": tipo_acao,
                    "selector": seletor,
                    "variable_key": str(passo.get("variavel") or ""),
                    "value_template": str(passo.get("valor") or ""),
                    "current_url": before_state["current_url"],
                    "current_host": before_state["current_host"],
                    "title": before_state["page_title"],
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "status": "running",
                }
                step_trace.append(trace_item)

                logging.info(f"[DESKTOP-REPLAY] Executando passo: {tipo_acao} em {seletor}")
                await run_session_checkpoint(page, "before_step_auth_check", current_step_diagnostic)

                if tipo_acao in ["clicar", "preencher", "extrair_texto", "download_pdf"] and seletor:
                    try:
                        await page.locator(seletor).first.wait_for(state="visible", timeout=15000)
                    except Exception:
                        logging.debug(f"[DESKTOP-REPLAY] Timeout de visibilidade para {seletor}. Tentando fallback...")

                try:
                    if tipo_acao == "clicar":
                        elementos = await learned_click_locator(page, passo)
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
                            await validate_or_allow_learned_microsoft_step(
                                    nova_aba,
                                    next_step_diagnostic,
                                    "after_new_page_check",
                                )
                            page = nova_aba
                            logging.info(f"[NAVEGAÇÃO] Popup/Nova Aba detetada! Foco transferido para: {page.url}")

                        except ActionPageError:
                            raise
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
                        await validate_or_allow_learned_microsoft_step(
                                page,
                                next_step_diagnostic,
                                "after_step_stability_check",
                            )

                    elif tipo_acao == "preencher":
                        variable_key = str(passo.get("variavel") or "").strip()
                        canonical_variable_key = canonical_client_field_key(variable_key) or variable_key
                        if variable_key and dados_variaveis and canonical_variable_key in dados_variaveis:
                            valor_final = str(dados_variaveis[canonical_variable_key])
                        else:
                            valor_final = str(passo.get("valor", ""))
                        elementos = page.locator(seletor)
                        quantidade = await elementos.count()
                        sucesso_preencher = False

                        for i in range(quantidade):
                            if await elementos.nth(i).is_visible():
                                await elementos.nth(i).fill(valor_final, timeout=5000)
                                valor_lido = await elementos.nth(i).input_value(timeout=5000)
                                if valor_lido != valor_final:
                                    raise RuntimeError(
                                        f"input_verification_failed: {variable_key} esperado={valor_final!r} lido={valor_lido!r}"
                                    )
                                sucesso_preencher = True
                                break

                        if not sucesso_preencher:
                            await elementos.first.fill(valor_final, timeout=5000, force=True)
                            valor_lido = await elementos.first.input_value(timeout=5000)
                            if valor_lido != valor_final:
                                raise RuntimeError(
                                    f"input_verification_failed: {variable_key} esperado={valor_final!r} lido={valor_lido!r}"
                                )

                    elif tipo_acao == "teclar":
                        await page.keyboard.press(str(passo.get("valor", "")))
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            pass

                    elif tipo_acao == "extrair_texto":
                        extraction_name = str(passo.get("nome") or passo.get("target_label") or "").strip() or seletor
                        strategy = str(passo.get("extraction_strategy") or "").strip().lower()
                        if (strategy == "near_label" or not seletor) and extraction_name:
                            final_dom_for_label = await page.content()
                            final_text_for_label = await page.locator("body").inner_text(timeout=5000)
                            texto = extract_value_near_label(final_dom_for_label, extraction_name) or extract_value_near_label(
                                final_text_for_label,
                                extraction_name,
                            )
                        else:
                            elemento = page.locator(seletor).first
                            tag_name = await elemento.evaluate("el => el.tagName.toLowerCase()")

                            if tag_name in ["input", "textarea"]:
                                texto = await elemento.input_value(timeout=5000)
                                if not texto:
                                    texto = await elemento.get_attribute("value", timeout=5000) or ""
                            else:
                                texto = await elemento.inner_text(timeout=5000)
                        dados_extraidos[extraction_name] = texto.strip()

                    elif tipo_acao == "download_pdf":
                        caminho_arquivo = runtime_download_path(nome_acao, run_id, ".pdf")
                        await _extrator_universal_de_download(page, seletor, str(caminho_arquivo))
                        metadata = runtime_file_metadata(caminho_arquivo)
                        downloaded_files.append(metadata)
                        arquivos_baixados.append(str(metadata["path"]))
                    expected_selector = str(
                        passo.get("expected_selector_after")
                        or (next_step.get("seletor") if isinstance(next_step, dict) else "")
                        or ""
                    ).strip()
                    if not expected_selector and isinstance(next_step, dict) and str(next_step.get("tipo") or "").strip().lower() == "extrair_texto":
                        contract = extraction_contract_from_action(action_config)
                        selector_data = contract.get("selector_data") if isinstance(contract, dict) else {}
                        expected_selector = str(selector_data.get("primary") or "").strip() if isinstance(selector_data, dict) else ""
                    if is_query_submit:
                        await verify_query_result_refresh(
                            page,
                            result_selector_for_query,
                            step_index,
                            before_url=query_before_url,
                            before_html=query_before_html,
                            navigation_observed=navigation_observed,
                        )
                    elif expected_selector and tipo_acao != "extrair_texto":
                        await verify_postcondition(page, expected_selector, step_index)
                    after_state = await current_browser_state(page)
                    overlay_waits_applied = await apply_reviewed_overlay_waits(page, step_index)
                    trace_item.update(
                        {
                            "status": "success",
                            "elapsed_ms": max(0, int((time.monotonic() - step_started_at) * 1000)),
                            "current_url": after_state["current_url"],
                            "current_host": after_state["current_host"],
                            "title": after_state["page_title"],
                        }
                    )
                    if overlay_waits_applied:
                        trace_item["reviewed_overlay_waits"] = overlay_waits_applied
                    last_successful_step_index = step_index

                except ActionPageError as e:
                    screenshot_path = await capture_error_screenshot(page, step_index, tipo_acao)
                    after_state = await current_browser_state(page)
                    trace_item.update(
                        {
                            "status": "error",
                            "elapsed_ms": max(0, int((time.monotonic() - step_started_at) * 1000)),
                            "current_url": after_state["current_url"],
                            "current_host": after_state["current_host"],
                            "title": after_state["page_title"],
                            "screenshot_path": screenshot_path,
                            "error_message": "Falha de pagina operacional.",
                        }
                    )
                    try:
                        page_error = await build_step_failure_diagnostics(
                            page,
                            step_index,
                            passo,
                            e,
                            screenshot_path=screenshot_path,
                        )
                        e.diagnostics.update(page_error)
                    except Exception:
                        pass
                    raise
                except Exception as e:
                    screenshot_path = await capture_error_screenshot(page, step_index, tipo_acao)
                    after_state = await current_browser_state(page)
                    trace_item.update(
                        {
                            "status": "error",
                            "elapsed_ms": max(0, int((time.monotonic() - step_started_at) * 1000)),
                            "current_url": after_state["current_url"],
                            "current_host": after_state["current_host"],
                            "title": after_state["page_title"],
                            "screenshot_path": screenshot_path,
                            "error_message": str(e)[:1000] or type(e).__name__,
                        }
                    )
                    wrapped = Exception(
                        f"Falha técnica no replay ao executar {tipo_acao} em {seletor}: {str(e)}"
                    )
                    wrapped.diagnostics = await build_step_failure_diagnostics(
                        page,
                        step_index,
                        passo,
                        e,
                        screenshot_path=screenshot_path,
                    )
                    raise wrapped from e
                finally:
                    if is_query_submit:
                        try:
                            page.remove_listener("framenavigated", observe_main_frame_navigation)
                        except Exception:
                            pass

            await asyncio.sleep(1)
            await run_session_checkpoint(page, "final_auth_check")
            validate_action_page_url(action_config, page.url)
            screenshot_path_result = ""
            evidence_name = ""
            try:
                await page.screenshot(path=str(caminho_execucao), full_page=False)
                screenshot_path_result = str(caminho_execucao.relative_to(_raiz_projeto()))
                evidence_name = caminho_execucao.name
            except Exception as exc:
                _LOGGER.warning(
                    "[DESKTOP-REPLAY] Falha ao salvar screenshot final da execução '%s': %s",
                    nome_acao,
                    type(exc).__name__,
                )
            try:
                await page.screenshot(path=str(caminho_evidencia_padrao), full_page=False)
            except Exception as exc:
                _LOGGER.warning(
                    "[DESKTOP-REPLAY] Falha ao salvar evidencia padrao da execução '%s': %s",
                    nome_acao,
                    type(exc).__name__,
                )
            final_title = (await page.title()).strip()[:200]
            final_page_text = ""
            final_page_dom = ""
            try:
                final_page_text = (await page.locator("body").inner_text(timeout=5000)).strip()[:20000]
            except Exception:
                final_page_text = ""
            try:
                final_page_dom = (await page.content()).strip()[:50000]
            except Exception:
                final_page_dom = ""
            query_result_confirmed = query_result_matches_inputs(final_page_text, dados_variaveis)
            if not query_result_confirmed:
                raise RuntimeError("query_result_not_confirmed: a pagina final nao corresponde aos dados do cliente")
            extraction_attention: dict[str, Any] = {}
            contract = extraction_contract_from_action(action_config if isinstance(action_config, dict) else {})
            if contract:
                contract_result = extract_with_contract(final_page_dom, final_page_text, contract)
                contract_value = str(contract_result.get("value") or "").strip()
                contract_key = str(
                    contract.get("target_name")
                    or contract.get("screen_label")
                    or contract.get("selected_text")
                    or "resultado"
                ).strip()
                if contract_key and contract_value:
                    dados_extraidos[contract_key] = contract_value
                if contract_result.get("needs_attention"):
                    extraction_attention = {
                        "needs_attention": True,
                        "contract": contract,
                        "validation": contract_result.get("validation", {}),
                        "candidate": contract_result.get("candidate", {}),
                    }
            _LOGGER.info(f"[DESKTOP-REPLAY] Execução finalizada com evidência: {caminho_execucao.name}")
            result_payload = {
                "status": "sucesso",
                "evidencia": evidence_name,
                "screenshot_path": screenshot_path_result,
                "arquivos_baixados": arquivos_baixados,
                "downloaded_files": downloaded_files,
                "main_file": downloaded_files[0] if downloaded_files else None,
                "dados_extraidos": dados_extraidos,
                "passos_executados": sum(1 for item in step_trace if item.get("status") == "success"),
                "passos_pulados": skipped_steps,
                "workflow_state_initial": workflow_state,
                "final_page": {"title": final_title, "url": _safe_result_url(page.url)},
                "final_page_text": final_page_text,
                "final_page_dom": final_page_dom,
                "session_state": last_session_state or "authenticated_system",
                "recovery_attempts": total_recovery_attempts,
                "recovery_steps": recovery_steps,
                "recovery_attempted": recovery_attempted,
                "operator_action_required": False,
                "last_page_title": last_page_title,
                "current_host": current_host,
                "query_completed_for": {
                    key: str(dados_variaveis.get(key) or "")
                    for key in ("grupo", "cota", "versao")
                    if dados_variaveis.get(key) is not None
                },
                "query_result_confirmed": query_result_confirmed,
                "checkpoint_diagnostics": checkpoint_diagnostics,
                "step_trace": step_trace,
                "last_successful_step_index": last_successful_step_index,
                "browser_mode": browser_mode,
                "runner": "desktop_browser_replay",
                "whether_desktop_browser_used": True,
            }
            if extraction_attention:
                result_payload["extraction_attention"] = extraction_attention
            return result_payload
    except SessionGuardianError as exc:
        _LOGGER.info(f"[ERRO] Sessao invalida na execução rápida '{nome_acao}': {exc}")
        exc.diagnostics.setdefault("step_trace", step_trace)
        exc.diagnostics.setdefault("last_successful_step_index", last_successful_step_index)
        return {"status": "erro", "motivo": str(exc), "page_diagnostics": exc.diagnostics}
    except ActionPageError as exc:
        _LOGGER.info(f"[ERRO] Falha operacional na execução rápida '{nome_acao}': {exc}")
        exc.diagnostics.setdefault("step_trace", step_trace)
        exc.diagnostics.setdefault("last_successful_step_index", last_successful_step_index)
        return {"status": "erro", "motivo": str(exc), "page_diagnostics": exc.diagnostics}
    except Exception as exc:
        _LOGGER.info(f"[ERRO] Falha na execução rápida '{nome_acao}': {exc}")
        diagnostics = getattr(exc, "diagnostics", None)
        if isinstance(diagnostics, dict):
            diagnostics.setdefault("reason", str(exc)[:1000] or type(exc).__name__)
            diagnostics.setdefault("exception_type", type(exc).__name__)
            original_exc = exc.__cause__ if exc.__cause__ is not None else exc
            diagnostics.setdefault("exception_message", str(original_exc)[:1000] or type(original_exc).__name__)
            diagnostics.setdefault("step_trace", step_trace)
            diagnostics.setdefault("last_successful_step_index", last_successful_step_index)
            diagnostics.setdefault("browser_mode", browser_mode)
            diagnostics.setdefault("runner", "desktop_browser_replay")
            diagnostics.setdefault("whether_desktop_browser_used", True)
            return {"status": "erro", "motivo": str(exc), "page_diagnostics": diagnostics}
        state = {"current_url": "", "current_host": "", "page_title": ""}
        try:
            state = await current_browser_state(page)
        except Exception:
            pass
        return {
            "status": "erro",
            "motivo": f"Falha na execução rápida: {exc}",
            "page_diagnostics": {
                **state,
                "reason": str(exc)[:1000] or type(exc).__name__,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc)[:1000] or type(exc).__name__,
                "step_trace": step_trace,
                "last_successful_step_index": last_successful_step_index,
                "browser_mode": browser_mode,
                "runner": "desktop_browser_replay",
                "whether_desktop_browser_used": True,
                "retryable": False,
            },
        }
    finally:
        if browser is not None and provider.close_browser_on_session_end:
            await browser.close()
