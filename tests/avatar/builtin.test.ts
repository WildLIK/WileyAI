import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { avatarFile } from "../../desktop/avatar-file.cjs";

test("built-in selection follows the installation while custom VRMs stay selected", () => {
  const selected = "builtin:fairy";
  for (const resources of ["C:/WileyAI/resources", "D:/New WileyAI/resources"])
    assert.equal(
      avatarFile(selected, resources),
      path.join(resources, "avatars", "Fairy_Assistant.vrm"),
    );
  assert.equal(avatarFile("D:/my model.VRM", "resources"), "D:/my model.VRM");
  assert.equal(avatarFile("", "resources"), null);
  assert.equal(avatarFile("builtin:unknown", "resources"), null);
});
