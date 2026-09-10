import { test } from "node:test";
import assert from "node:assert/strict";
import { openAccessProfileWorkspace } from "../src/lib/access-profile-workspace";

test("Autenticar navega para o workspace com o perfil antes da autenticação", async () => {
  const calls: string[] = [];
  await openAccessProfileWorkspace(
    "profile-x",
    (options) => {
      calls.push(`${options.to}?access_profile_id=${options.search.access_profile_id}`);
    },
    async (profileId) => {
      calls.push(`authenticate:${profileId}`);
    },
  );
  assert.deepEqual(calls, [
    "/configuracoes/navegador?access_profile_id=profile-x",
    "authenticate:profile-x",
  ]);
});
