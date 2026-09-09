"""Resolve preparation choices before allocating a recording session."""
from sqlalchemy import select

from backend.db import ClientList, DataSource, SessionLocal
from backend.services.access_profiles import list_access_profiles
from backend.services.external_systems import load_current_external_system


class TeachingContextError(ValueError):
    pass


def resolve_teaching_context(*, profile_id=None, spreadsheet_id=None, list_ids=None, tenant_id="default"):
    system = load_current_external_system()
    system_id = system.get("id")
    if not system_id:
        raise TeachingContextError("Configure o sistema antes de ensinar uma ação.")
    profiles = [p for p in list_access_profiles(tenant_id=tenant_id, external_system_id=system_id) if p["active"]]
    selected_lists = list(dict.fromkeys(list_ids or []))
    with SessionLocal() as db:
        if spreadsheet_id:
            sheet = db.get(DataSource, spreadsheet_id)
            if not sheet or sheet.source_type != "system_spreadsheet":
                raise TeachingContextError("Escolha uma planilha válida.")
            list_id = (sheet.configuration or {}).get("default_list_id")
            if not list_id:
                raise TeachingContextError("Vincule a planilha a uma lista antes de continuar.")
            selected_lists = [list_id]
        rows = list(db.scalars(select(ClientList).where(ClientList.id.in_(selected_lists), ClientList.tenant_id == tenant_id, ClientList.active.is_(True)))) if selected_lists else []
        if len(rows) != len(selected_lists):
            raise TeachingContextError("Uma das listas não está disponível.")
        if any(not row.access_profile_id for row in rows):
            raise TeachingContextError("Vincule o acesso responsável pela lista para continuar.")
        inherited = {row.access_profile_id for row in rows}
        if len(inherited) > 1:
            raise TeachingContextError("As listas escolhidas pertencem a acessos diferentes.")
        if inherited:
            inherited_id = next(iter(inherited))
            if profile_id and profile_id != inherited_id:
                raise TeachingContextError("Esta lista pertence a outro acesso.")
            profile_id = inherited_id
    if not profile_id and len(profiles) == 1:
        profile_id = profiles[0]["id"]
    profile = next((p for p in profiles if p["id"] == profile_id), None)
    if not profile:
        raise TeachingContextError("Escolha o acesso responsável pela ação.")
    strategy = system.get("run_start_strategy")
    if strategy not in {"external_entry_each_run", "persistent_graph_reentry"}:
        raise TeachingContextError("Configure o início das execuções no sistema.")
    if strategy == "external_entry_each_run" and not (system.get("entry_url") or system.get("external_login_url")):
        raise TeachingContextError("Configure a URL de entrada do sistema.")
    return {"external_system_id": system_id, "required_access_profile_id": profile_id, "access_name": profile["display_name"], "allowed_list_ids": selected_lists, "run_start_strategy": strategy}
