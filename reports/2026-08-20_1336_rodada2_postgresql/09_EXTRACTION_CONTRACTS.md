# Extraction Contracts

Contagem no banco: 2.

Conclusão: os contratos de extração passaram a viver junto da `action_version`.
Evidência: `extraction_contracts` com `action_version_id` e `example_value`/`summary_instruction`.
Estado: parcial, mas funcional.
Impacto: o fluxo de revisão já não depende do JSON operacional.

Observação: um contrato herdado veio sem exemplo explícito; o teste unitário da rodada valida preservação literal de `"032"` na montagem do contrato.
