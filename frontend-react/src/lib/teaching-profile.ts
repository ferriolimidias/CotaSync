import type { AccessProfile } from "../types/api";

export function teachingProfiles(profiles: AccessProfile[], systemId?: string) {
  return profiles.filter((profile) => profile.active && Boolean(systemId) && profile.external_system_id === systemId);
}

export function compatibleTeachingList(listProfileId: string | null | undefined, profileId: string) {
  return Boolean(profileId && listProfileId === profileId);
}

export function restoredTeachingProfile(session: { access_profile_id?: unknown }) {
  return typeof session.access_profile_id === "string" ? session.access_profile_id : "";
}

export function teachingProfileStatus(status?: string) {
  if (status === "verified") return "Verificado";
  if (status === "available") return "Disponível";
  if (status === "reauth_required") return "Reautenticação necessária";
  if (status === "not_found") return "Conta não encontrada";
  return "Não verificado";
}
