import { test } from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import { AvatarArm } from "../../src/avatarArm.ts";
import { fairyPoses } from "../../src/avatarPoses.ts";
import { AvatarMotion } from "../../src/avatarMotion.ts";
import { idleAvatar } from "../../src/avatarBehavior.ts";

function fixture(side: "left" | "right") {
  const sign = side === "left" ? 1 : -1;
  const scene = new THREE.Group();
  const nodes = new Map<string, THREE.Bone>();
  const bone = (
    name: string,
    parent: THREE.Object3D,
    x: number,
    y: number,
    z: number,
  ) => {
    const b = new THREE.Bone();
    b.position.set(x, y, z);
    parent.add(b);
    nodes.set(side + name, b);
    return b;
  };
  const upper = bone("UpperArm", scene, sign * 0.15, 1.3, 0);
  const lower = bone("LowerArm", upper, sign * 0.25, 0, 0);
  const hand = bone("Hand", lower, sign * 0.22, 0, 0);
  for (const [i, digit] of ["Index", "Middle", "Ring", "Little"].entries()) {
    const a = bone(
      digit + "Proximal",
      hand,
      sign * 0.055,
      0.007,
      0.02 - i * 0.015,
    );
    const b = bone(digit + "Intermediate", a, sign * 0.03, 0, 0);
    bone(digit + "Distal", b, sign * 0.02, 0, 0);
  }
  const a = bone("ThumbMetacarpal", hand, sign * 0.004, -0.01, 0.016);
  const b = bone("ThumbProximal", a, sign * 0.035, -0.002, 0.03);
  bone("ThumbDistal", b, sign * 0.023, -0.001, 0.018);
  scene.updateMatrixWorld(true);
  const vrm = {
    scene,
    humanoid: { getNormalizedBoneNode: (name: string) => nodes.get(name) },
    expressionManager: { getExpression: () => null, setValue: () => {} },
    update: () => {},
  } as unknown as VRM;
  const arm = new AvatarArm(vrm, side, 1.7, 0);
  const point = (digit: string) => {
    scene.updateMatrixWorld(true);
    return hand.worldToLocal(
      nodes.get(side + digit + "Distal")!.getWorldPosition(new THREE.Vector3()),
    );
  };
  return { sign, scene, nodes, upper, lower, hand, arm, point, vrm };
}

test("both hands curl toward the palm, keep the pointing finger extended and reset every finger axis", () => {
  for (const side of ["left", "right"] as const) {
    const f = fixture(side);
    const goal: [number, number, number] = [f.sign * 0.22, 0.64, 0.2];
    f.arm.update(goal, [0, 0, 0], "open", 1, 0);
    const open = f.point("Middle");
    f.arm.update(goal, [0, 0, 0], "fist", 1, 0);
    const closed = f.point("Middle");
    assert.ok(
      closed.y < open.y - 0.025,
      side + " fingers must fold into the palm",
    );
    assert.ok(
      (open.x - closed.x) * f.sign > 0.025,
      side + " fist must visibly shorten the fingers",
    );
    f.arm.update(goal, [0, 0, 0], "point", 1, 0);
    assert.ok((f.point("Index").x - f.point("Middle").x) * f.sign > 0.025);
    f.arm.reset(1);
    for (const [name, node] of f.nodes)
      if (/Thumb|Index|Middle|Ring|Little/.test(name))
        assert.ok(node.quaternion.angleTo(new THREE.Quaternion()) < 1e-6);
  }
});

test("cycling poses cannot accumulate arm roll or bend either wrist backwards", () => {
  for (const side of ["left", "right"] as const) {
    const f = fixture(side);
    const samples: THREE.Quaternion[][] = [];
    for (let cycle = 0; cycle < 8; cycle++) {
      for (const name of [
        "thumbsup",
        "think",
        "shy",
        "praise",
        "wave",
      ] as const) {
        const p = fairyPoses[name];
        for (let i = 0; i < 240; i++) {
          f.arm.update(
            p[side],
            p[`${side}Wrist`],
            p[`${side}Hand`],
            0.12,
            0,
            p[`${side}Elbow`],
            p[`${side}Palm`],
          );
          assert.ok(
            f.hand.quaternion.angleTo(new THREE.Quaternion()) <= 0.851,
            side + " wrist exceeds its flexion limit",
          );
          assert.ok(f.lower.quaternion.toArray().every(Number.isFinite));
        }
      }
      samples.push([
        f.upper.quaternion.clone(),
        f.lower.quaternion.clone(),
        f.hand.quaternion.clone(),
      ]);
    }
    for (const sample of samples.slice(1))
      for (let i = 0; i < 3; i++)
        assert.ok(
          sample[i].angleTo(samples[0][i]) < 0.003,
          side + " arm rolled after repeating the same pose cycle",
        );
  }
});

test("idle arms cross below the chest with relaxed fingers and anatomical elbows at every viewing angle", () => {
  for (const side of ["left", "right"] as const) {
    const f = fixture(side);
    const p = fairyPoses.none;
    for (const yaw of [0, Math.PI / 2, Math.PI, -Math.PI / 2]) {
      f.scene.rotation.y = yaw;
      f.scene.updateMatrixWorld(true);
      for (let i = 0; i < 180; i++)
        f.arm.update(
          p[side],
          p[`${side}Wrist`],
          p[`${side}Hand`],
          0.15,
          0,
          p[`${side}Elbow`],
          p[`${side}Palm`],
        );
      const elbow = f.scene.worldToLocal(
        f.lower.getWorldPosition(new THREE.Vector3()),
      );
      const wrist = f.scene.worldToLocal(
        f.hand.getWorldPosition(new THREE.Vector3()),
      );
      assert.ok(
        elbow.y < 1.17 && elbow.y > 0.93,
        side + " elbow must stay below the shoulder: " + elbow.toArray(),
      );
      assert.ok(elbow.z > 0.005, side + " elbow must not fold behind the body");
      assert.ok(
        elbow.x * f.sign > 0.085,
        side + " elbow must stay on its anatomical side",
      );
      assert.ok(
        wrist.y > 1.04 && wrist.y < 1.18,
        side + " wrist must rest below the bust",
      );
      assert.ok(
        wrist.x * f.sign < -0.03,
        side + " forearm must cross the centreline",
      );
      assert.ok(f.lower.quaternion.toArray().every(Number.isFinite));
      const clasp = f.point("Middle");
      f.arm.update(
        p[side],
        p[`${side}Wrist`],
        "open",
        1,
        0,
        p[`${side}Elbow`],
        p[`${side}Palm`],
      );
      const open = f.point("Middle");
      assert.ok(
        clasp.y < open.y - 0.015,
        side + " relaxed clasp must bend the fingers",
      );
    }
  }
  assert.equal(fairyPoses.nod.leftPalm, fairyPoses.none.leftPalm);
  assert.equal(fairyPoses.wave.rightElbow, undefined);
  assert.equal(fairyPoses.wave.rightPalm, undefined);
});

test("raised and folded arms reach their goals without a half-turn at either shoulder", () => {
  for (const side of ["left", "right"] as const) {
    const f = fixture(side);
    for (const yaw of [0, Math.PI / 2, Math.PI, -Math.PI / 2]) {
      f.scene.rotation.y = yaw;
      for (const name of [
        "none",
        "joy",
        "praise",
        "listen",
        "wave",
        "think",
        "none",
      ] as const) {
        const p = fairyPoses[name];
        for (let i = 0; i < 180; i++) {
          f.arm.update(
            p[side],
            p[`${side}Wrist`],
            p[`${side}Hand`],
            0.15,
            0,
            p[`${side}Elbow`],
            p[`${side}Palm`],
          );
        }
        f.scene.updateMatrixWorld(true);
        const root = f.upper.getWorldPosition(new THREE.Vector3());
        const elbow = f.lower.getWorldPosition(new THREE.Vector3());
        const rotation = f.scene.getWorldQuaternion(new THREE.Quaternion());
        const restAxis = new THREE.Vector3(f.sign, 0, 0).applyQuaternion(
          rotation,
        );
        const minimalSwing = new THREE.Quaternion()
          .setFromUnitVectors(restAxis, elbow.clone().sub(root).normalize())
          .multiply(rotation);
        const actual = f.upper.getWorldQuaternion(new THREE.Quaternion());
        assert.ok(
          actual.angleTo(minimalSwing) < 0.802,
          `${side} ${name}: excessive axial shoulder rotation`,
        );
        const goal = new THREE.Vector3(...p[side]).multiplyScalar(1.7);
        const localRoot = f.scene.worldToLocal(root.clone());
        const wrist = f.scene.worldToLocal(
          f.hand.getWorldPosition(new THREE.Vector3()),
        );
        // Goals within 75% of the 0.47 reach are met exactly; farther ones
        // are deliberately eased short to keep a soft elbow (softReach).
        if (goal.distanceTo(localRoot) < 0.47 * 0.75)
          assert.ok(
            wrist.distanceTo(goal) < 0.004,
            `${side} ${name}: shoulder limit lost the wrist goal`,
          );
      }
    }
  }
});

test("automatic music releases the folded idle arms and reaches the same dance as the manual preview", () => {
  for (const side of ["left", "right"] as const) {
    const fixtures = [fixture(side), fixture(side)];
    const animators = fixtures.map((f) => {
      const floor = new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.01, 0.01));
      floor.position.y = 0.005;
      f.scene.add(floor);
      return new AvatarMotion(f.vrm, 1.7);
    });
    for (let frame = 0; frame < 180; frame++) {
      const time = (frame + 1) / 60;
      for (let index = 0; index < 2; index++)
        animators[index].update(
          time,
          1 / 60,
          index
            ? { ...idleAvatar, gesture: "dance", cue: "dance" }
            : idleAvatar,
          {
            motion: true,
            expressions: true,
            gaze: false,
            pointer: { x: 0, y: 0 },
            yaw: 0,
            demo: Boolean(index),
            music: {
              active: true,
              source: "fixture",
              level: 0.5,
              beat: 0.3,
              bpm: 120,
              phase: time * 2,
              error: "",
            },
          },
        );
    }
    const [automatic, manual] = fixtures;
    for (const key of ["upper", "lower", "hand"] as const)
      assert.ok(
        automatic[key].quaternion.angleTo(manual[key].quaternion) < 0.003,
        side + " music retained an idle arm constraint",
      );
    for (const f of fixtures)
      f.scene.traverse((o) => {
        if (o instanceof THREE.Mesh) o.geometry.dispose();
      });
  }
});

test("an out-of-reach hand goal keeps a soft elbow instead of locking the arm straight", async () => {
  const { softReach } = await import("../../src/avatarArm.ts");
  assert.equal(softReach(0.5, 1), 0.5);
  assert.equal(softReach(0.75, 1), 0.75);
  let previous = 0;
  for (const distance of [0.8, 0.9, 1, 1.3, 3]) {
    const reached = softReach(distance, 1);
    assert.ok(reached > previous, "monotonic");
    assert.ok(reached < 0.9, `${distance} → ${reached}`);
    previous = reached;
  }
});
