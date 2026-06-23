# Relatório: aprendizado guiado com retorno de dados e arquivos

Data: 2026-06-23 15:01 BRT
Commit base: `3b17b9633f3e53a024d2157c2d4be312d7865919`

## Auditoria obrigatória

### 1. Recursos reutilizáveis encontrados

- Extração determinística por passos `extrair_texto`, com nome lógico e seletor gravado.
- Download PDF robusto em três camadas: evento Playwright, requisição autenticada e fallback de blob/base64.
- Validação de PDF por existência, tamanho e assinatura `%PDF-`.
- Conversão de tabelas PDF para Excel com `pdfplumber` e `pandas`.
- Exportação e download de CSV/Excel no fluxo de operação em lote.
- Screenshots de aprendizado, replay, erro e evidência final.
- Detecção de download durante a observação ao vivo.
- Persistência de `dados_extraidos`, `result_payload`, `operational_summary` e `technical_summary` nas runs.
- Exibição existente de arquivos, PDF, Excel, dados extraídos e evidências no Streamlit.
- Resumo operacional determinístico, com fallback opcional por OpenAI e filtros contra conteúdo técnico/sensível.

### 2. Arquivos, funções e classes encontradas

- `backend/motor_browser.py`: `_extrator_universal_de_download`, `_arquivo_pdf_valido`, `_arquivo_pdf_pronto_e_integro`, `_converter_pdf_para_excel`, `executar_acao_rapida`.
- `backend/services/demo_session.py`: `DemoBrowserSession.download_detected`, `_record_live_step`, `stop_recording`, `save_action`, `execute_action` e capturas de evidência.
- `backend/services/ai_observer.py`: observação ao vivo, síntese local/IA e contexto sanitizado.
- `backend/services/action_runner.py`: criação/atualização da run e filtragem de `result_payload`.
- `backend/services/operational_summary.py`: extração de resultados úteis, templates, resumo determinístico e fallback IA.
- `backend/agente.py`: quick action, payload de dados/arquivos e recuperação de falhas.
- `frontend/app.py`: download de PDF/Excel, exibição de dados extraídos, evidência e `operational_summary`.
- `backend/main.py` e `frontend/app.py`: geração/exportação de relatórios CSV da operação em lote.

### 3. O que foi reutilizado agora

- O downloader PDF existente é chamado tanto pelo fast-track quanto pelo replay de sessão.
- A extração continua sendo executada pelos passos determinísticos existentes.
- Os downloads continuam chegando ao chat pelo campo legado `arquivos`, além dos novos metadados estruturados.
- A UI reutiliza `st.download_button` e o volume compartilhado do projeto.
- A síntese usa o observador existente, agora com a instrução guiada e candidatos reais do DOM.
- Evidências, runs e resumos continuam no fluxo atual.

### 4. Lacunas encontradas

- A gravação iniciava sem objetivo de negócio estruturado.
- A síntese recebia passos, mas não objetivo, entradas, critério de sucesso ou tipo de retorno.
- Não havia configuração pós-gravação para selecionar candidatos do DOM ou informar uma extração manual.
- Download detectado durante o aprendizado não era convertido em passo persistente de download.
- Runs não tinham contrato padronizado `downloaded_files`/`main_file`.
- A recuperação por IA do fluxo legado não respeitava uma opção por ação.

### 5. O que não foi duplicado

- Não foi criado outro downloader, conversor PDF, gerador de relatório, repositório de runs ou sistema de resumo.
- Não foi criado endpoint paralelo de execução nem framework novo de UI.
- Não foram alterados login externo, noVNC, Modo operador, controles de colagem ou providers.

## Implementação

### Aprendizado guiado

Antes de iniciar a gravação, a UI solicita nome, objetivo, entradas, resultado esperado, critério de sucesso, tipo de retorno e política de IA na execução. Esses dados seguem para a sessão e são persistidos em:

- `objective`
- `input_description`
- `expected_result`
- `success_criteria`
- `output_type`
- `output_schema`
- `extraction_targets`
- `user_result_summary_template`
- `ai_result_summary_enabled`
- `ai_recovery_enabled`

A execução de novas ações é determinística por padrão. IA continua ativa no aprendizado/síntese quando configurada no ambiente.

### Síntese e configuração de saída

Ao parar a gravação:

- tarefas pendentes do observador são consolidadas;
- a página final fornece candidatos visíveis de saída;
- a síntese recebe objetivo, entradas, resultado, critério, tipo de retorno, passos, eventos e candidatos;
- a UI mostra passos, síntese e metadados editáveis;
- o usuário pode selecionar candidatos, informar rótulo/seletor manual ou escolher o texto visível da página final.

As extrações selecionadas são salvas como passos `extrair_texto` e executadas sem OpenAI.

### Downloads e PDFs

Quando o usuário confirma o retorno de arquivo após um download detectado, o clique correspondente é salvo como `download_pdf`. O arquivo é gravado somente em runtime em `data/runs/downloads/`, agora ignorado pelo Git.

O payload contém:

- `arquivos`: compatibilidade com o chat atual;
- `downloaded_files`: nome, caminho relativo seguro, MIME e tamanho;
- `main_file`: arquivo principal.

O `action_runner` rejeita caminhos absolutos, travessia de diretórios e metadados fora da pasta de runtime. A UI resolve o caminho somente dentro da pasta permitida e oferece botão de download sem mostrar o caminho.

### Resposta operacional e uso de IA

- Extração configurada: resumo mostra somente valores úteis.
- Dados e arquivo: resumo inclui `Arquivo disponível.`
- Somente arquivo: `Arquivo gerado com sucesso. Arquivo disponível.`
- Sem extração/arquivo configurado: `Ação executada com sucesso, mas nenhum resultado final foi configurado para retorno.`
- Página/login incorretos mantêm os erros de domínio e reautenticação existentes.
- `ai_result_summary_enabled=false`: OpenAI não é chamado para resumir.
- `ai_recovery_enabled=false`: falha determinística não aciona auto-healing.
- Sem chave OpenAI: síntese e resumo usam fallback determinístico.

## Testes

- `python3 -m compileall backend frontend scripts`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`: serviços ativos; desktop browser healthy.
- `curl -s http://127.0.0.1:8100/health`: `status=ok`.
- `docker exec cotasync_test_backend python -m unittest discover -s tests -v`: 32 testes passaram.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py`: 3 ciclos Browserless e revalidação passaram.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`: CDP/noVNC, Modo operador, aprendizado, extração e replay passaram.

Cobertura adicionada:

1. Metadados guiados são persistidos.
2. Objetivo e resultado esperado chegam à síntese.
3. Ausência de saída usa o resumo operacional definido.
4. Extração determinística chega a `dados_extraidos`.
5. Download detectado vira passo de arquivo, gera metadados e resumo de arquivo.
6. Quick execution mantém `operational_summary`.
7. Resumo IA desabilitado não instancia OpenAI.
8. Fallback sem chave OpenAI permanece funcional.
9. Filtros existentes contra tokens, credenciais, seletores e caminhos inseguros continuam cobertos.
10. Demo Browserless permanece funcional.
11. Runner desktop continua rejeitando Google/domínio incorreto.

## Passos para demonstração manual

1. Em `Chat & Ações`, abra uma sessão e conclua o login manual.
2. Preencha o bloco `Aprendizado guiado` com objetivo, entradas, saída e política de IA.
3. Inicie a gravação e execute a rotina real no noVNC/Modo operador.
4. Pare a gravação e revise passos, síntese e candidatos de resultado.
5. Selecione dados para extração e/ou `Retornar arquivo baixado`.
6. Salve a ação, informe os valores das variáveis e execute o replay.
7. Verifique o resumo, os dados extraídos, o botão de arquivo e a nova run em `/api/runs`.

## Limites atuais

- A associação automática de um download ao passo usa o evento detectado e, como fallback, o último clique gravado; deve ser revisada pelo usuário antes de salvar.
- O download estruturado desta entrega é PDF, reutilizando a validação existente. Outros formatos continuam possíveis pelo fluxo legado, mas não recebem validação de conteúdo específica.
- O fallback `texto visível da tela final` pode retornar texto amplo; seletores específicos produzem respostas melhores.
- Candidatos automáticos dependem de elementos visíveis no DOM da página final.

Próximo passo recomendado: demonstrar uma ação real com um resultado textual pequeno e um PDF, validar os rótulos na UI e então ampliar a seleção pós-gravação para múltiplos downloads/formatos conforme casos reais.
