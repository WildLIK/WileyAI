import { test } from "node:test";
import assert from "node:assert/strict";
import { besideAvatar } from "../../desktop/avatar-layout.cjs";

test("the separate pose controls stay alongside the fairy on negative-origin and narrow displays", () => {
  for (const [bounds, area] of [
    [
      { x: 1500, y: 800, width: 480, height: 740 },
      { x: 0, y: 0, width: 1920, height: 1040 },
    ],
    [
      { x: -1600, y: -800, width: 480, height: 740 },
      { x: -1920, y: -1080, width: 1920, height: 1040 },
    ],
    [
      { x: 0, y: 0, width: 900, height: 740 },
      { x: 0, y: 0, width: 1024, height: 768 },
    ],
    [
      { x: 400, y: 400, width: 480, height: 740 },
      { x: 0, y: 0, width: 1280, height: 720 },
    ],
  ]) {
    const { avatar, tool } = besideAvatar(bounds, area);
    assert.ok(
      avatar.x + avatar.width <= tool.x || tool.x + tool.width <= avatar.x,
    );
    for (const row of [avatar, tool]) {
      assert.ok(row.x >= area.x && row.y >= area.y);
      assert.ok(row.x + row.width <= area.x + area.width);
      assert.ok(row.y + row.height <= area.y + area.height);
    }
  }
});
