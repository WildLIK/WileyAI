import { test } from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import {
  VRMSpringBoneJoint,
  VRMSpringBoneManager,
  type VRM,
} from "@pixiv/three-vrm";
import {
  AvatarMotion,
  facingV3,
  influentialBones,
  pruneSpringBones,
  vrmFacing,
} from "../../src/avatarMotion.ts";
import { AvatarArm } from "../../src/avatarArm.ts";
import { fairyPoses } from "../../src/avatarPoses.ts";
import { idleAvatar, type AvatarSignal } from "../../src/avatarBehavior.ts";
import { fitAvatarCamera } from "../../src/avatarPresentation.ts";

const halfTurn = new THREE.Quaternion(0, 1, 0, 0);

/**
 * A humanoid in VRM 1.0 layout (+Z forward, left at +X), or the same body as
 * a VRM 0.x file (-Z forward) after VRMUtils.rotateVRM0 turned its scene.
 */
function rig(version: "0" | "1") {
  const m = version === "0" ? -1 : 1;
  const scene = new THREE.Group();
  if (version === "0") scene.rotation.y = Math.PI;
  const nodes = new Map<string, THREE.Bone>();
  const bone = (
    name: string,
    parent: THREE.Object3D,
    x: number,
    y: number,
    z: number,
  ) => {
    const b = new THREE.Bone();
    b.name = name;
    b.position.set(x * m, y, z * m);
    parent.add(b);
    nodes.set(name, b);
    return b;
  };
  const hips = bone("hips", scene, 0, 0.9, 0.01);
  const spine = bone("spine", hips, 0, 0.1, 0);
  const chest = bone("chest", spine, 0, 0.15, 0);
  const neck = bone("neck", chest, 0, 0.2, 0);
  bone("head", neck, 0, 0.08, 0.01);
  for (const [side, s] of [
    ["left", 1],
    ["right", -1],
  ] as const) {
    const shoulder = bone(side + "Shoulder", chest, s * 0.04, 0.15, 0);
    const upper = bone(side + "UpperArm", shoulder, s * 0.08, 0, 0);
    const lower = bone(side + "LowerArm", upper, s * 0.25, 0, 0);
    const hand = bone(side + "Hand", lower, s * 0.22, 0, 0);
    for (const [i, digit] of ["Index", "Middle", "Ring", "Little"].entries()) {
      const a = bone(
        side + digit + "Proximal",
        hand,
        s * 0.055,
        0.007,
        0.02 - i * 0.015,
      );
      const b = bone(side + digit + "Intermediate", a, s * 0.03, 0, 0);
      bone(side + digit + "Distal", b, s * 0.02, 0, 0);
    }
    const a = bone(side + "ThumbMetacarpal", hand, s * 0.004, -0.01, 0.016);
    const b = bone(side + "ThumbProximal", a, s * 0.035, -0.002, 0.03);
    bone(side + "ThumbDistal", b, s * 0.023, -0.001, 0.018);
    const leg = bone(side + "UpperLeg", hips, s * 0.08, -0.05, 0);
    const knee = bone(side + "LowerLeg", leg, 0, -0.4, 0);
    bone(side + "Foot", knee, 0, -0.4, 0.02);
  }
  const floor = new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.01, 0.01));
  floor.position.y = 0.005;
  scene.add(floor);
  scene.updateMatrixWorld(true);
  const values = new Map<string, number>();
  const vrm = {
    scene,
    meta: { metaVersion: version },
    humanoid: { getNormalizedBoneNode: (name: string) => nodes.get(name) },
    expressionManager: {
      getExpression: () => ({}),
      setValue: (name: string, value: number) => values.set(name, value),
    },
    update: () => {},
  } as unknown as VRM;
  return { scene, nodes, vrm, values, floor };
}

function assertSameBody(
  a: ReturnType<typeof rig>,
  b: ReturnType<typeof rig>,
  label: string,
) {
  a.scene.updateMatrixWorld(true);
  b.scene.updateMatrixWorld(true);
  for (const [name, node] of a.nodes) {
    const other = b.nodes.get(name)!;
    const p = node.getWorldPosition(new THREE.Vector3());
    const q = other.getWorldPosition(new THREE.Vector3());
    assert.ok(
      p.distanceTo(q) < 1e-5,
      `${label}: ${name} ${p.toArray()} vs ${q.toArray()}`,
    );
    // Same visible orientation; the VRM 0.x bone frames are a half turn apart.
    const expected = node
      .getWorldQuaternion(new THREE.Quaternion())
      .multiply(halfTurn);
    const actual = other.getWorldQuaternion(new THREE.Quaternion());
    assert.ok(expected.angleTo(actual) < 1e-4, `${label}: ${name} rotation`);
  }
}

test("VRM 0.x is detected from its meta and mirrors X/Z components only", () => {
  assert.equal(vrmFacing({ meta: { metaVersion: "0" } }), -1);
  assert.equal(vrmFacing({ meta: { metaVersion: "1" } }), 1);
  assert.equal(vrmFacing({}), 1);
  assert.deepEqual(facingV3([0.1, -0.2, 0.3], -1), [-0.1, -0.2, -0.3]);
  const same = facingV3([0.1, -0.2, -0], 1);
  assert.deepEqual(same, [0.1, -0.2, -0]);
  assert.ok(Object.is(same[2], -0), "VRM 1.0 values stay bit-identical");
});

test("VRM 0.x arms reach the same visible goals with the same palms and fingers", () => {
  for (const side of ["left", "right"] as const) {
    const one = rig("1"),
      zero = rig("0");
    const arms = [one, zero].map((f) => new AvatarArm(f.vrm, side, 1.7, 0));
    for (const name of [
      "none",
      "think",
      "thumbsup",
      "wave",
      "point",
      "shy",
    ] as const) {
      const p = fairyPoses[name];
      for (let i = 0; i < 30; i++)
        for (const arm of arms)
          arm.update(
            p[side],
            p[`${side}Wrist`],
            p[`${side}Hand`],
            0.2,
            0,
            p[`${side}Elbow`],
            p[`${side}Palm`],
          );
      assertSameBody(one, zero, `${side} ${name}`);
    }
  }
});

test("VRM 0.x body motion matches VRM 1.0: arms stay down, nods, legs and skirt", () => {
  const one = rig("1"),
    zero = rig("0");
  const motions = [one, zero].map((f) => new AvatarMotion(f.vrm, 1.7));
  // The fallback rest pose lowers both arms instead of raising them.
  assertSameBody(one, zero, "rest");
  const run = (
    from: number,
    frames: number,
    signal: AvatarSignal,
    extra: object = {},
  ) => {
    for (let i = 0; i < frames; i++)
      for (const motion of motions)
        motion.update((from + i) / 60, 1 / 60, signal, {
          motion: true,
          gaze: true,
          expressions: true,
          pointer: { x: 0.4, y: -0.3 },
          yaw: 0.2,
          ...extra,
        });
  };
  run(0, 90, idleAvatar);
  assertSameBody(one, zero, "idle");
  run(90, 90, { ...idleAvatar, gesture: "nod", cue: "nod" });
  assertSameBody(one, zero, "nod");
  run(180, 90, { ...idleAvatar, phase: "listening" });
  assertSameBody(one, zero, "listen");
  assert.ok(one.values.get("skirtRaiseLeft")! > 0.3);
  assert.equal(
    zero.values.get("skirtRaiseLeft"),
    one.values.get("skirtRaiseLeft"),
  );
  run(270, 120, idleAvatar, {
    music: {
      active: true,
      source: "fixture",
      level: 0.5,
      beat: 0.4,
      bpm: 120,
      phase: 0,
      error: "",
    },
  });
  assertSameBody(one, zero, "dance");
  run(390, 30, { ...idleAvatar, gesture: "think", cue: "t" });
  assertSameBody(one, zero, "think");
  run(420, 10, idleAvatar, { motion: false, gaze: false });
  assertSameBody(one, zero, "reduced motion");
});

test("springs that move no vertex are pruned; weighted, rigid and constrained chains stay", () => {
  const build = (constrained: boolean) => {
    const scene = new THREE.Group();
    const root = new THREE.Bone(),
      weighted = new THREE.Bone(),
      hairA = new THREE.Bone(),
      hairB = new THREE.Bone(),
      ribbonA = new THREE.Bone(),
      ribbonB = new THREE.Bone(),
      charm = new THREE.Bone();
    scene.add(root);
    root.add(weighted, hairA, ribbonA, charm);
    hairA.add(hairB);
    ribbonA.add(ribbonB);
    hairB.position.y = ribbonB.position.y = -0.1;
    // A rigid accessory moves with its bone without any skin weight.
    charm.add(new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.01, 0.01)));
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute([0, 0, 0, 0, 1, 0, 1, 0, 0], 3),
    );
    // Indices 2 and 3 (the hair) appear only with zero weight.
    geometry.setAttribute(
      "skinIndex",
      new THREE.Uint16BufferAttribute([1, 2, 0, 0, 5, 3, 0, 0, 0, 2, 0, 0], 4),
    );
    geometry.setAttribute(
      "skinWeight",
      new THREE.Float32BufferAttribute(
        [1, 0, 0, 0, 0.5, 0, 0.5, 0, 1, 0, 0, 0],
        4,
      ),
    );
    const mesh = new THREE.SkinnedMesh(geometry);
    scene.add(mesh);
    const skeleton = new THREE.Skeleton([
      root,
      weighted,
      hairA,
      hairB,
      ribbonA,
      ribbonB,
    ]);
    mesh.bind(skeleton);
    scene.updateMatrixWorld(true);
    const manager = new VRMSpringBoneManager();
    const joints = {
      hairA: new VRMSpringBoneJoint(hairA, hairB),
      hairB: new VRMSpringBoneJoint(hairB, null),
      ribbonA: new VRMSpringBoneJoint(ribbonA, ribbonB),
      ribbonB: new VRMSpringBoneJoint(ribbonB, null),
      charm: new VRMSpringBoneJoint(charm, null),
    };
    for (const joint of Object.values(joints)) manager.addJoint(joint);
    manager.setInitState();
    const vrm = {
      scene,
      springBoneManager: manager,
      nodeConstraintManager: constrained
        ? { constraints: new Set([{ source: hairB }]) }
        : undefined,
    } as unknown as VRM;
    return { scene, manager, joints, vrm, bones: { weighted, hairA, ribbonB } };
  };
  const plain = build(false);
  const used = influentialBones(plain.scene);
  assert.ok(used.has(plain.bones.weighted) && used.has(plain.bones.ribbonB));
  assert.ok(!used.has(plain.bones.hairA), "zero weights do not count");
  assert.equal(pruneSpringBones(plain.vrm), 2);
  assert.deepEqual(
    [...plain.manager.joints],
    [plain.joints.ribbonA, plain.joints.ribbonB, plain.joints.charm],
  );
  assert.equal(plain.bones.hairA.matrixAutoUpdate, true);
  assert.equal(plain.bones.ribbonB.matrixAutoUpdate, false);
  plain.manager.update(1 / 60);
  assert.equal(pruneSpringBones(plain.vrm), 0, "pruning is idempotent");
  const constrained = build(true);
  assert.equal(pruneSpringBones(constrained.vrm), 0);
  assert.equal(pruneSpringBones({ scene: new THREE.Group() } as never), 0);
});

test("reduced motion restarts springs once from rest instead of whipping them", () => {
  const f = rig("1");
  let resets = 0;
  (f.vrm as unknown as { springBoneManager: object }).springBoneManager = {
    reset: () => resets++,
  };
  const motion = new AvatarMotion(f.vrm, 1.7);
  const options = {
    motion: true,
    gaze: false,
    expressions: true,
    pointer: { x: 0, y: 0 },
    yaw: 0,
  };
  for (let i = 0; i < 10; i++)
    motion.update(i / 60, 1 / 60, idleAvatar, options);
  assert.equal(resets, 0);
  for (let i = 10; i < 20; i++)
    motion.update(i / 60, 1 / 60, idleAvatar, { ...options, motion: false });
  assert.equal(resets, 1);
  motion.update(1, 1 / 60, idleAvatar, options, true);
  assert.equal(resets, 1);
});

test("refitting an unchanged camera skips the projection update without changing the result", () => {
  const bounds = new THREE.Box3(
    new THREE.Vector3(-0.8, 0, -0.1),
    new THREE.Vector3(0.8, 1.8, 0.1),
  );
  const camera = new THREE.PerspectiveCamera(30, 0.7, 0.1, 20);
  let updates = 0;
  const original = camera.updateProjectionMatrix.bind(camera);
  camera.updateProjectionMatrix = () => {
    updates++;
    original();
  };
  const head = new THREE.Vector3(0, 1.6, 0);
  fitAvatarCamera(camera, bounds, 3, head);
  fitAvatarCamera(camera, bounds, 3, head);
  assert.equal(updates, 1);
  camera.aspect = 1.2;
  fitAvatarCamera(camera, bounds, 3, head);
  assert.equal(updates, 2);
  const fresh = new THREE.PerspectiveCamera(30, 1.2, 0.1, 20);
  fitAvatarCamera(fresh, bounds, 3, head);
  assert.deepEqual(
    camera.projectionMatrix.toArray(),
    fresh.projectionMatrix.toArray(),
  );
  assert.deepEqual(camera.position.toArray(), fresh.position.toArray());
  assert.equal(head.y, 1.6, "the head position is not mutated");
});
