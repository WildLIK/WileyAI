import { test } from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import {
  avatarPhase,
  avatarReaction,
  AvatarActivity,
  avatarZoom,
  idleAvatar,
} from "../../src/avatarBehavior.ts";
import { AvatarMotion } from "../../src/avatarMotion.ts";
import { fitAvatarCamera } from "../../src/avatarPresentation.ts";
import {
  AvatarSignals,
  AvatarDemos,
  fitWindow,
  nextDisplayBounds,
} from "../../desktop/avatar.cjs";
import { AvatarArm } from "../../src/avatarArm.ts";

test("the reference poses distinguish praise, joy, attention, explanation and sympathy", () => {
  assert.equal(
    avatarReaction("Ты милая, но у меня ничего не получается").gesture,
    "comfort",
  );
  assert.equal(avatarReaction("Ты не молодец").gesture, "none");
  for (const [phrase, gesture] of [
    ["Ура, у меня получилось!", "joy"],
    ["Уайли, ты такая милая", "cute"],
    ["Привет, Уайли!", "wave"],
    ["Объясни, как это работает", "explain"],
    ["Давай подумаем над этим", "think"],
    ["Ты молодец, отлично помогла!", "praise"],
    ["Что мне нужно сделать дальше?", "point"],
    ["Послушай меня внимательно", "listen"],
    ["Всё верно, так и сделаем", "thumbsup"],
    ["Ты смущаешься?", "shy"],
    ["Ты устала? Пора отдохнуть", "tired"],
    ["Мне грустно, ничего не получается", "comfort"],
  ])
    assert.equal(avatarReaction(phrase).gesture, gesture, phrase);
});

test("conversation energy grows with recent turns and settles without replaying history", () => {
  const activity = new AvatarActivity();
  assert.equal(activity.value(0), 0);
  const first = activity.mark(1000);
  for (let now = 2000; now <= 6000; now += 1000) activity.mark(now);
  assert.ok(activity.value(6000) > first);
  assert.ok(activity.value(40000) < activity.value(6000));
  assert.equal(activity.value(70000), 0);
});

test("arm reach stays finite and preserves limb lengths when a hand target is out of reach", () => {
  const scene = new THREE.Group(),
    upper = new THREE.Bone(),
    lower = new THREE.Bone(),
    hand = new THREE.Bone();
  scene.add(upper);
  upper.add(lower);
  lower.add(hand);
  upper.position.set(-0.2, 1.4, 0);
  lower.position.x = -0.3;
  hand.position.x = -0.28;
  scene.updateMatrixWorld(true);
  const vrm = {
    scene,
    humanoid: {
      getNormalizedBoneNode: (name: string) =>
        name === "rightUpperArm"
          ? upper
          : name === "rightLowerArm"
            ? lower
            : name === "rightHand"
              ? hand
              : null,
    },
  } as unknown as VRM;
  const arm = new AvatarArm(vrm, "right", 1.8, 0);
  for (let i = 0; i < 80; i++)
    arm.update([-0.12, 0.85, 0.12], [0, 0, 0], "point", 0.3, 0);
  scene.updateMatrixWorld(true);
  const actual = hand.getWorldPosition(new THREE.Vector3());
  assert.ok(actual.distanceTo(new THREE.Vector3(-0.216, 1.53, 0.216)) < 0.02);
  arm.update([-5, 5, 5], [0, 0, 0], "open", 1, 0);
  scene.updateMatrixWorld(true);
  assert.ok(hand.getWorldPosition(actual).toArray().every(Number.isFinite));
  assert.equal(lower.position.length().toFixed(3), "0.300");
  assert.equal(hand.position.length().toFixed(3), "0.280");
});

test("text cues are restrained; a failed result is not celebrated", () => {
  assert.equal(avatarReaction("Привет!").gesture, "wave");
  assert.equal(avatarReaction("Привет! Рада помочь.").gesture, "wave");
  assert.equal(
    avatarReaction("Температура воздуха три градуса.").emotion,
    "neutral",
  );
  assert.equal(avatarReaction("Ого!").emotion, "surprised");
  assert.equal(avatarReaction("Спасибо, получилось.").emotion, "happy");
  assert.equal(
    avatarReaction("Опять не получилось, я расстроен.").emotion,
    "sad",
  );
  assert.equal(
    avatarReaction("Погода: 3.7 °C, осадки 88%.").emotion,
    "neutral",
  );
  assert.equal(
    avatarPhase({ playing: false, thinking: true, listening: true }),
    "thinking",
  );
  assert.equal(
    avatarPhase({ playing: true, thinking: true, listening: true }),
    "speaking",
  );
});

test("the shared state survives another window's idle heartbeat and expires closed sources", () => {
  let now = 0;
  const signals = new AvatarSignals(
    () => {},
    () => now,
  );
  signals.update(1, { ...idleAvatar, phase: "speaking", voice: true });
  signals.update(2, idleAvatar);
  assert.equal(signals.state().phase, "speaking");
  assert.equal(signals.state().voice, true);
  signals.update(3, { ...idleAvatar, phase: "thinking" });
  signals.release(1);
  assert.equal(signals.state().voice, false);
  assert.equal(signals.state().phase, "thinking");
  now = 16000;
  assert.equal(signals.state().phase, "idle");
  assert.throws(() =>
    signals.update(1, { ...idleAvatar, cue: "x".repeat(81) }),
  );
  assert.throws(() => signals.update(1, { ...idleAvatar, phase: "__proto__" }));
});

test("zoom stays bounded and targets the upper body without changing model scale", () => {
  assert.equal(avatarZoom(NaN), 1);
  assert.equal(avatarZoom(10), 6);
  assert.equal(avatarZoom(-10), 0.7);
  const camera = new THREE.PerspectiveCamera(30, 0.7, 0.1, 20);
  const bounds = new THREE.Box3(
    new THREE.Vector3(-0.8, 0, -0.1),
    new THREE.Vector3(0.8, 1.8, 0.1),
  );
  fitAvatarCamera(camera, bounds, 2);
  assert.equal(camera.zoom, 2);
  assert.ok(camera.position.y > 0.9, "the closeup moves up toward the face");
  fitAvatarCamera(camera, bounds, 6, new THREE.Vector3(0, 1.6, 0));
  assert.equal(camera.zoom, 6);
  assert.ok(camera.position.y > 1.6 && camera.position.y < 1.8);
  assert.ok(
    Math.abs(camera.getWorldDirection(new THREE.Vector3()).y) < 0.001,
    "the face remains frontal at maximum zoom",
  );
});

test("manual previews share one owner, expire and never replace conversation state", () => {
  let now = 0;
  const demos = new AvatarDemos(
    () => {},
    () => now,
  );
  const face = {
    signal: { ...idleAvatar, emotion: "happy", cue: "a" },
    strength: 0.8,
    still: true,
    label: "Радость",
  };
  demos.update(1, face);
  assert.equal(demos.state(1).owner, true);
  assert.equal(demos.state(2).demo?.signal.emotion, "happy");
  demos.update(2, { ...face, signal: { ...face.signal, emotion: "sad" } });
  demos.update(1, face, true);
  assert.equal(demos.state(1).owner, false);
  assert.equal(
    demos.state(1).demo?.signal.emotion,
    "sad",
    "a stale heartbeat cannot reclaim the preview",
  );
  demos.release(1);
  assert.ok(demos.state(2).demo);
  demos.release(2);
  assert.equal(demos.state(1).demo, null);
  assert.throws(() => demos.update(1, { ...face, strength: NaN }));
  demos.update(1, face);
  now = 16000;
  assert.equal(demos.state(2).demo, null);
});

test("normalized bones and expressions ease back to neutral and close the mouth immediately", () => {
  const head = new THREE.Object3D(),
    rightArm = new THREE.Object3D(),
    values = new Map<string, number>();
  const scene = new THREE.Group();
  const wing = new THREE.Bone();
  wing.name = "L_wing_0";
  scene.add(wing);
  const vrm = {
    scene,
    humanoid: {
      getNormalizedBoneNode: (name: string) =>
        name === "head" ? head : name === "rightUpperArm" ? rightArm : null,
    },
    expressionManager: {
      getExpression: () => ({}),
      setValue: (name: string, value: number) => values.set(name, value),
    },
    update: () => {},
  } as unknown as VRM;
  const animator = new AvatarMotion(vrm, 1.8);
  assert.equal(animator.wingCount, 1);
  const options = {
    motion: true,
    gaze: true,
    expressions: true,
    pointer: { x: 1, y: 0 },
    yaw: 0,
  };
  animator.update(
    1,
    0.1,
    {
      ...idleAvatar,
      phase: "speaking",
      emotion: "happy",
      gesture: "wave",
      cue: "hello",
    },
    options,
  );
  animator.update(
    2,
    0.1,
    {
      ...idleAvatar,
      phase: "speaking",
      emotion: "happy",
      gesture: "wave",
      cue: "hello",
    },
    options,
  );
  assert.ok(head.rotation.y > 0);
  assert.notEqual(wing.quaternion.y, 0);
  assert.equal(
    rightArm.rotation.z,
    1.1,
    "an incomplete arm chain keeps its rest pose",
  );
  assert.ok(values.get("aa")! > 0 && values.get("happy")! > 0);
  animator.update(3, 0.1, idleAvatar, {
    ...options,
    motion: false,
    gaze: false,
    expressions: false,
  });
  assert.equal(values.get("aa"), 0);
  assert.equal(values.get("ou"), 0);
  assert.deepEqual(scene.position.toArray(), [0, 0, 0]);
  assert.equal(wing.quaternion.y, 0);
});

test("display changes preserve relative placement and recover from unplugged / differently scaled monitors", () => {
  const left = { x: -1920, y: -120, width: 1920, height: 1080 };
  const right = { x: 0, y: 0, width: 1280, height: 680 };
  const bounds = { x: -360, y: 390, width: 360, height: 570 };
  assert.deepEqual(nextDisplayBounds(bounds, left, right), {
    x: 920,
    y: 110,
    width: 360,
    height: 570,
  });
  assert.deepEqual(fitWindow(bounds, right), {
    x: 0,
    y: 110,
    width: 360,
    height: 570,
  });
  assert.deepEqual(
    fitWindow({ x: 5000, y: -5000, width: 360, height: 570 }, left),
    { x: -360, y: -120, width: 360, height: 570 },
  );
});
