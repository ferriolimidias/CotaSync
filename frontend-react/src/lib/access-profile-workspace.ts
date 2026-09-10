export type ProfileWorkspaceNavigate = (options: {
  to: "/configuracoes/navegador";
  search: { access_profile_id: string; access_cycle_id: string };
}) => Promise<unknown> | unknown;

export type ProfileWorkspaceAuthenticate = (accessProfileId: string) => Promise<{ access_cycle_id: string }>;

export async function openAccessProfileWorkspace(
  accessProfileId: string,
  navigate: ProfileWorkspaceNavigate,
  startCycle: ProfileWorkspaceAuthenticate,
) {
  const cycle = await startCycle(accessProfileId);
  await navigate({ to: "/configuracoes/navegador", search: { access_profile_id: accessProfileId, access_cycle_id: cycle.access_cycle_id } });
  return cycle;
}
