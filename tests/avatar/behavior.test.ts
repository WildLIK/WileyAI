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
import { avatarPointer } from "../../src/avatarPointer.ts";
import { dancePose } from "../../src/avatarDance.ts";
import { avatarCaption } from "../../src/avatarCaption.ts";
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
    ["Уайли, ты такая милая", "shy"],
    ["Вот это неожиданно!", "surprise"],
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

test("ordinary feelings vary without preset wording; negation and quoted text do not act as mood", () => {
  for (const [text, emotion] of [
    ["Сегодня я весела и довольна прогулкой.", "happy"],
    ["Я рад, что мы снова разговариваем.", "happy"],
    ["Я устала, хочу спать.", "relaxed"],
    ["Сейчас мне одиноко и тяжело на душе.", "sad"],
    ["Я злюсь, меня это раздражает!", "angry"],
    ["Я удивлена, вот это поворот!", "surprised"],
    ["Мне не грустно, я радуюсь.", "happy"],
    ["Мне не грустно.", "neutral"],
    ["В документе написано «я счастлива».", "neutral"],
  ])
    assert.equal(avatarReaction(text).emotion, emotion, text);
});

test("global pointer keeps moving on the same side outside a small window", () => {
  const canvas = { width: 350, height: 500 },
    face = { x: 175, y: 120 };
  const a = avatarPointer(
    { x: 500, y: 200, width: 1920, height: 1080 },
    face,
    canvas,
  );
  const b = avatarPointer(
    { x: 1100, y: 400, width: 1920, height: 1080 },
    face,
    canvas,
  );
  assert.ok(a.x > 0 && a.x < b.x && b.x < 1);
  assert.ok(a.y < b.y);
  assert.equal(
    avatarPointer(
      { x: -20000, y: -20000, width: 1920, height: 1080 },
      face,
      canvas,
    ).x,
    -1,
  );
});

test("dance interpolates continuous finite poses and yields to speech, hidden motion and pause", () => {
  assert.notDeepEqual(dancePose(0).left, dancePose(6).left);
  assert.deepEqual(dancePose(0), dancePose(16));
  for (let phase = 0; phase < 16; phase += 0.1) {
    const before = dancePose(phase),
      after = dancePose(phase + 0.01);
    assert.ok(
      before.left.every(
        (value, i) =>
          Number.isFinite(value) && Math.abs(value - after.left[i]) < 0.01,
      ),
    );
  }
  const scene = new THREE.Group(),
    head = new THREE.Object3D();
  const vrm = {
    scene,
    humanoid: {
      getNormalizedBoneNode: (name: string) => (name === "head" ? head : null),
    },
    update: () => {},
  } as unknown as VRM;
  const motion = new AvatarMotion(vrm, 1.8);
  const music = {
    active: true,
    source: "AIMP",
    level: 0.7,
    beat: 0.9,
    phase: 3,
    bpm: 120,
    error: "",
  };
  const options = {
    motion: true,
    gaze: true,
    expressions: true,
    pointer: { x: 0, y: 0 },
    yaw: 0,
    music,
  };
  for (let i = 0; i < 30; i++)
    motion.update(i / 30, 1 / 30, idleAvatar, options);
  assert.equal(motion.pose, "dance");
  for (let i = 0; i < 60; i++)
    motion.update(
      1 + i / 30,
      1 / 30,
      { ...idleAvatar, phase: "speaking" },
      options,
    );
  assert.equal(motion.pose, "explain");
  for (let i = 0; i < 60; i++)
    motion.update(3 + i / 30, 1 / 30, idleAvatar, {
      ...options,
      music: { ...music, active: false },
    });
  assert.equal(motion.pose, "none");
  motion.update(6, 0.1, idleAvatar, { ...options, motion: false });
  assert.equal(motion.pose, "none");
});

test("three dances have distinct limb motion; full turns stay smooth across loop boundaries", () => {
  assert.notDeepEqual(dancePose(6, 1), dancePose(6, 2));
  assert.notDeepEqual(dancePose(6, 2), dancePose(6, 3));
  assert.ok((dancePose(8, 2).turn || 0) > Math.PI);
  assert.ok(Math.abs(dancePose(3, 3).shift?.[0] || 0) > 0.01);
  const scene = new THREE.Group();
  const vrm = {
    scene,
    humanoid: { getNormalizedBoneNode: () => null },
    update: () => {},
  } as unknown as VRM;
  const motion = new AvatarMotion(vrm, 1.8);
  const options = {
    motion: true,
    gaze: false,
    expressions: true,
    pointer: { x: 0, y: 0 },
    yaw: 0,
    demo: true,
  };
  let previous = 0;
  for (let i = 0; i < 600; i++) {
    motion.update(
      i / 60,
      1 / 60,
      { ...idleAvatar, gesture: "dance2", cue: "spin" },
      options,
    );
    assert.ok(Math.abs(scene.rotation.y - previous) < 0.12);
    previous = scene.rotation.y;
  }
  assert.ok(scene.rotation.y > 6);
  assert.equal(
    avatarCaption("thumbsup", "happy", "idle").text,
    "Всё верно, так и сделаем",
  );
  assert.equal(avatarCaption("dance3", "happy", "idle").name, "Танец 3");
  assert.equal(
    avatarCaption("surprise", "surprised", "idle").name,
    "Удивление",
  );
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

test("skirt lift tracks blended leg angles even with facial expressions disabled and returns to rest", () => {
  const scene = new THREE.Group();
  const left = new THREE.Bone(),
    right = new THREE.Bone();
  scene.add(left, right);
  const values = new Map<string, number>();
  const vrm = {
    scene,
    humanoid: {
      getNormalizedBoneNode: (name: string) =>
        name === "leftUpperLeg"
          ? left
          : name === "rightUpperLeg"
            ? right
            : null,
    },
    expressionManager: {
      getExpression: (name: string) =>
        name.startsWith("skirtRaise") ? {} : null,
      setValue: (name: string, value: number) => values.set(name, value),
    },
    update: () => {},
  } as unknown as VRM;
  const motion = new AvatarMotion(vrm, 1.8);
  const options = {
    motion: true,
    gaze: false,
    expressions: false,
    pointer: { x: 0, y: 0 },
    yaw: 0,
  };
  for (let i = 0; i < 90; i++)
    motion.update(
      i / 60,
      1 / 60,
      { ...idleAvatar, phase: "listening" },
      options,
    );
  assert.ok(values.get("skirtRaiseLeft")! > 0.49);
  assert.ok(
    Math.abs(values.get("skirtRaiseLeft")! - -left.rotation.x / 1.1) < 1e-9,
  );
  assert.ok(
    Math.abs(values.get("skirtRaiseRight")! - -right.rotation.x / 1.1) < 1e-9,
  );
  for (let i = 0; i < 180; i++)
    motion.update(2 + i / 60, 1 / 60, idleAvatar, options);
  assert.ok(values.get("skirtRaiseLeft")! < 0.3);
  assert.ok(values.get("skirtRaiseRight")! < 0.4);
  for (let i = 0; i < 180; i++)
    motion.update(5 + i / 60, 1 / 60, idleAvatar, {
      ...options,
      motion: false,
    });
  assert.ok(values.get("skirtRaiseLeft")! < 0.001);
  assert.ok(values.get("skirtRaiseRight")! < 0.001);
});
