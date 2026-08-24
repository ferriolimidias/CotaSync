# BrowserWorkspace UX

Alteração: `BrowserWorkspace` passou a usar altura responsiva baseada no viewport, preservando o card visual mas priorizando área útil do navegador.

Desktop alvo: a altura mínima fica limitada por `calc(100vh - 9rem)`/`calc(100vh - 12rem)`, melhorando operação em 1366x768 e aproveitando mais espaço em telas maiores.

Teste: E2E React abriu o token noVNC e encontrou o iframe `Navegador CotaSync`.

Pendente: validação manual de ergonomia durante login real no sistema externo.
