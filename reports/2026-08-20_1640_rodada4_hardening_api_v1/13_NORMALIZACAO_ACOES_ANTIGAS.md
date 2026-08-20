# Normalização Ações Antigas

Auditoria:
- `quantidade-de-parcelas`: `has_url=False`, `url_inicial=None`, `steps_count=1`, `legacy_unconfigured=True`, sem variáveis.
- `quantidade-de-parcelas-2`: `has_url=True`, URL Microsoft/login, `steps_count=8`, variáveis `grupo`, `cota`, `vers_o`, `legacy_unconfigured=False`.

Arquivo: `backend/services/actions_repository.py`
Função/endpoint: `_action_steps` no runner aceita `robust_steps` ou `passos_playwright`.
Antes: P2 indicava ausência de `initial_url/robust_steps`.
Depois: nenhuma normalização automática aplicada.
Motivo: `quantidade-de-parcelas` exigiria novo aprendizado; inventar URL seria inseguro.
Impacto: ação insegura continua marcada como attention/legacy.
Teste: auditoria direta via `find_action`.
Resultado: documentado.
Risco restante: rodada de aprendizado deve republicar ou aposentar ação antiga.
