import { test } from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { fitAvatarCamera } from "../../src/avatarPresentation.ts";

test("whole avatar remains inside portrait, narrow and wide panels", () => {
  for (const aspect of [0.35, 0.7, 1, 2.4]) {
    for (const dimensions of [
      [1.4, 1.8, 0.4],
      [3.6, 1.4, 0.8],
      [0.2, 0.25, 0.03],
    ]) {
      const center = new THREE.Vector3(0.08, 0.9, -0.03);
      const size = new THREE.Vector3(...dimensions);
      const box = new THREE.Box3().setFromCenterAndSize(center, size);
      const camera = new THREE.PerspectiveCamera(30, aspect, 0.1, 20);
      fitAvatarCamera(camera, box);
      for (const x of [box.min.x, box.max.x])
        for (const y of [box.min.y, box.max.y])
          for (const z of [box.min.z, box.max.z]) {
            const p = new THREE.Vector3(x, y, z).project(camera);
            assert.ok(
              Math.abs(p.x) < 0.92,
              `horizontal clipping at aspect ${aspect}`,
            );
            assert.ok(
              Math.abs(p.y) < 0.92,
              `vertical clipping at aspect ${aspect}`,
            );
            assert.ok(p.z > -1 && p.z < 1, "inside clipping planes");
          }
    }
  }
});

test("empty bounds leave the initial placeholder camera intact", () => {
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
  camera.position.set(0, 1.15, 3.1);
  fitAvatarCamera(camera, new THREE.Box3());
  assert.deepEqual(camera.position.toArray(), [0, 1.15, 3.1]);
});
