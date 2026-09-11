"""Shared structural preflight for operational action execution."""

from __future__ import annotations

from typing import Any

from backend.db import Action as DbAction, ActionVersion, Client, ClientList, ExternalAccessProfile, ExternalSystem, SessionLocal
from backend.services.learned_graph import validate_compiled_action_graph, validate_graph_reentrancy
from backend.services.start_policy import requires_external_entry, resolve_external_entry_url, validate_fresh_start_context


def _missing_variables(action: Any, variables: dict[str, Any]) -> list[str]:
    return [
        str(variable.key)
        for variable in getattr(action, "variables", []) or []
        if bool(getattr(variable, "required", True))
        and not str(variables.get(str(variable.key)) or "").strip()
    ]


def preflight_action_execution(
    action: Any,
    *,
    client_id: str | None = None,
    variables: dict[str, Any] | None = None,
    list_id: str | None = None,
    spreadsheet_id: str | None = None,
) -> dict[str, Any]:
    """Resolve and validate the same context before an individual or batch run."""
    variables = variables if isinstance(variables, dict) else {}
    with SessionLocal() as db:
        db_action = db.get(DbAction, str(action.id))
        if db_action is None or not db_action.published_version_id:
            return {"ok": False, "code": "action_not_published", "message": "A ação não possui uma versão publicada."}
        version = db.get(ActionVersion, db_action.published_version_id)
        if version is None or str(version.status or "").lower() not in {"published", "active"}:
            return {"ok": False, "code": "action_version_not_ready", "message": "A versão publicada da ação não está pronta."}

        resolved_list_id = str(list_id or "").strip() or None
        client = db.get(Client, str(client_id)) if client_id else None
        if client_id and (client is None or not client.active):
            return {"ok": False, "code": "client_not_available", "message": "Cliente não encontrado ou inativo."}
        if client is not None:
            resolved_list_id = str(client.list_id or "").strip() or None
        list_row = db.get(ClientList, resolved_list_id) if resolved_list_id else None
        if resolved_list_id and (list_row is None or not list_row.active):
            return {"ok": False, "code": "list_not_available", "message": "A lista do cliente não está disponível."}

        profile_id = str(version.required_access_profile_id or "").strip() or None
        if not profile_id and str(version.run_start_strategy or "").strip() == "external_entry_each_run":
            return {
                "ok": False,
                "code": "required_access_profile_not_assigned",
                "message": "A ação não possui usuário de acesso vinculado. Vincule um perfil antes de executar.",
            }
        if list_row and profile_id != str(list_row.access_profile_id or "").strip():
            return {
                "ok": False,
                "code": "profile_list_mismatch",
                "message": "A ação e a lista usam acessos diferentes.",
                "action_profile_id": profile_id,
                "list_profile_id": str(list_row.access_profile_id or "").strip() or None,
            }
        if client is not None and not list_row:
            return {"ok": False, "code": "client_context_missing", "message": "Este cliente ainda não possui uma lista configurada."}
        profile = db.get(ExternalAccessProfile, profile_id) if profile_id else None
        if profile_id and (profile is None or not profile.active):
            return {
                "ok": False,
                "code": "required_access_profile_not_assigned",
                "message": "A ação não possui usuário de acesso vinculado. Vincule um perfil antes de executar.",
            }
        if not profile_id:
            return {"ok": False, "code": "access_profile_required", "message": "A ação precisa de um acesso ativo."}
        system = db.get(ExternalSystem, profile.external_system_id)
        if system is None:
            return {"ok": False, "code": "external_system_missing", "message": "O sistema externo do acesso não está configurado."}

        strategy = str(version.run_start_strategy or "").strip()
        start_context = validate_fresh_start_context(
            strategy=strategy,
            entry_url=resolve_external_entry_url(system.config or {}),
            access_profile_id=profile_id,
        )
        if not start_context["valid"] and start_context.get("code") == "run_start_strategy_invalid":
            return {"ok": False, "code": "run_start_strategy_invalid", "message": "A estratégia de início da ação é inválida."}
        definition = dict(version.definition or {})
        graph = validate_compiled_action_graph(definition)
        if not graph["valid"]:
            return {
                "ok": False,
                "code": "main_graph_invalid",
                "message": "A ação não possui um grafo executável válido.",
                "graph_errors": graph["errors"],
            }
        if requires_external_entry(strategy):
            if not start_context["valid"] and start_context.get("code") == "entry_url_missing":
                return {"ok": False, "code": "entry_url_missing", "message": "A entrada do sistema não está configurada."}
            if not start_context["valid"] and start_context.get("code") == "access_profile_required":
                return {"ok": False, "code": "access_profile_required", "message": "A ação precisa de um acesso ativo."}
        else:
            reentrancy = validate_graph_reentrancy(definition)
            if not reentrancy["valid"]:
                return {"ok": False, "code": "main_graph_invalid", "message": "A ação não possui um grafo de reentrada válido."}

        missing = _missing_variables(action, variables)
        if client_id and missing:
            return {"ok": False, "code": "client_variables_missing", "message": "Variáveis obrigatórias ausentes: " + ", ".join(missing), "missing_variables": missing}
        allowed = {str(item) for item in (version.definition or {}).get("allowed_list_ids", db_action.allowed_list_ids or []) if str(item).strip()}
        if resolved_list_id and allowed and resolved_list_id not in allowed:
            return {"ok": False, "code": "list_scope_mismatch", "message": "Esta ação não está disponível para a lista do cliente."}
        return {
            "ok": True,
            "code": "ok",
            "action_id": str(action.id),
            "action_version_id": str(version.id),
            "client_id": str(client.id) if client else None,
            "list_id": resolved_list_id,
            "access_profile_id": profile_id,
            "external_system_id": str(system.id),
            "run_start_strategy": strategy,
        }
