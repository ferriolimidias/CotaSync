import { test } from "node:test";
import assert from "node:assert/strict";
import { compatibleTeachingList, restoredTeachingProfile, teachingProfiles, teachingProfileStatus } from "../src/lib/teaching-profile";

const profile = { id: "a", display_name: "Profile A", login_identifier: "a@example.test", active: true, external_system_id: "system-a" };

test("one active profile remains selectable with an unbound list", () => {
  assert.deepEqual(teachingProfiles([profile], "system-a"), [profile]);
  assert.equal(compatibleTeachingList(null, profile.id), false);
  assert.deepEqual(teachingProfiles([profile], "system-a"), [profile]);
});

for (const status of ["unknown", "unverified", "reauth_required", "not_found", "available"]) {
  test(`operational status ${status} never hides identity`, () => {
    assert.equal(teachingProfiles([{ ...profile, validation_status: status }], "system-a").length, 1);
  });
}

test("matching lists are selectable and other profiles are blocked", () => {
  assert.equal(compatibleTeachingList("a", "a"), true);
  assert.equal(compatibleTeachingList("b", "a"), false);
  assert.equal(compatibleTeachingList(null, "a"), false);
  assert.equal(compatibleTeachingList(null, ""), false);
});

test("three active profiles are visible; inactive and foreign-system profiles are excluded", () => {
  const profiles = [profile, { ...profile, id: "b", validation_status: "reauth_required" }, { ...profile, id: "c", validation_status: "unknown" }, { ...profile, id: "d", external_system_id: "system-b" }, { ...profile, id: "e", active: false }];
  assert.deepEqual(teachingProfiles(profiles, "system-a").map((item) => item.id), ["a", "b", "c"]);
  assert.equal(teachingProfiles(profiles, undefined).length, 0);
});

test("restored sessions show their actual binding without inventing a legacy binding", () => {
  assert.equal(restoredTeachingProfile({ access_profile_id: "a" }), "a");
  assert.equal(restoredTeachingProfile({ access_profile_id: null }), "");
  assert.equal(teachingProfileStatus("reauth_required"), "Reautenticação necessária");
});
