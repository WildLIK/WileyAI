import { test } from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { AvatarHeadHit } from "../../src/avatarHeadHit.ts";

test("pet target follows the head through rotation and rejects body/empty space", () => {
  const parent = new THREE.Group();
  const head = new THREE.Object3D();
  parent.add(head);
  head.position.set(0, 1.4, 0);
  const target = new AvatarHeadHit(head, 1.7);
  const ray = new THREE.Ray(
    new THREE.Vector3(0, 1.55, 3),
    new THREE.Vector3(0, 0, -1),
  );
  parent.updateMatrixWorld(true);
  assert.equal(target.contains(ray), true);
  ray.origin.set(0, 1.1, 3);
  assert.equal(target.contains(ray), false);
  ray.origin.set(0.35, 1.55, 3);
  assert.equal(target.contains(ray), false);
  parent.position.x = 0.4;
  head.rotation.z = -Math.PI / 3;
  parent.updateMatrixWorld(true);
  const centre = head.localToWorld(new THREE.Vector3(0, 1.7 * 0.085, 0));
  ray.origin.copy(centre).add(new THREE.Vector3(0, 0, 3));
  assert.equal(target.contains(ray), true);
  ray.direction.set(0, 0, 1);
  assert.equal(target.contains(ray), false);
});
