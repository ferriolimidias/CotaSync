export type ProfileWorkspaceNavigate = (options: {
  to: "/configuracoes/navegador";
  search: { access_profile_id: string };
}) => Promise<unknown> | unknown;

export type ProfileWorkspaceAuthenticate = (accessProfileId: string) => Promise<unknown>;

export async function openAccessProfileWorkspace(
  accessProfileId: string,
  navigate: ProfileWorkspaceNavigate,
  authenticate: ProfileWorkspaceAuthenticate,
) {
  await navigate({ to: "/configuracoes/navegador", search: { access_profile_id: accessProfileId } });
  return authenticate(accessProfileId);
}
