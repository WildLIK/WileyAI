import { test } from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import { danceStyle, followBeat } from "../../src/avatarDance.ts";
import { AvatarMotion } from "../../src/avatarMotion.ts";
import { idleAvatar } from "../../src/avatarBehavior.ts";
import type { MusicPulse } from "../../src/avatarMusic.ts";

const music = (phase: number, active = true): MusicPulse => ({
  active,
  source: "fixture",
  level: 0.5,
  beat: 0.3,
  bpm: 120,
  phase,
  error: "",
});
const options = (pulse: MusicPulse) => ({
  motion: true,
  gaze: false,
  expressions: true,
  pointer: { x: 0, y: 0 },
  yaw: 0,
  music: pulse,
});
const emptyRig = () =>
  ({
    scene: new THREE.Group(),
    humanoid: { getNormalizedBoneNode: () => null },
    update: () => {},
  }) as unknown as VRM;

test("the dance follows only the fractional beat error of the meter's ever-growing counter", () => {
  const smooth = 1 - Math.exp(-7 / 60);
  // A far-ahead counter (it also counts while she does not dance) moves the
  // dance by at most half a beat of correction, never by hundreds of beats.
  const next = followBeat(0, 537.3, 1 / 60, 120, smooth);
  assert.ok(next > 0 && next < 0.1, String(next));
  // Errors wrap to the nearest beat in both directions.
  assert.ok(followBeat(0, 10.9, 0, 120, 1) < 0, "0.9 ahead is 0.1 behind");
  assert.ok(Math.abs(followBeat(0, 10.9, 0, 120, 1) + 0.05) < 1e-9);
  assert.ok(Math.abs(followBeat(0, 3.2, 0, 120, 1) - 0.1) < 1e-9);
  // It converges onto the beat grid and survives a backend worker restart.
  let phase = 0;
  for (let frame = 0; frame < 600; frame++) {
    const time = frame / 60;
    const counter = frame < 300 ? 1000.37 + time * 2 : 0.81 + time * 2;
    const before = phase;
    phase = followBeat(phase, counter, 1 / 60, 120, smooth);
    assert.ok(phase - before > 0 && phase - before < 0.07, "no skipped beats");
    if (frame === 299 || frame === 599) {
      const error = ((((counter - phase) % 1) + 1.5) % 1) - 0.5;
      assert.ok(Math.abs(error) < 0.01, "locked to the beat: " + error);
    }
  }
  assert.ok(phase < 25, "about two beats per second, not the raw counter");
  assert.equal(danceStyle(-0.5), 3);
  assert.equal(danceStyle(0), 1);
  assert.equal(danceStyle(16), 2);
  assert.equal(danceStyle(47.9), 3);
});

test("music starting mid-song does not whirl through the meter's past beats", () => {
  const motion = new AvatarMotion(emptyRig(), 1.8);
  for (let frame = 0; frame < 60; frame++) {
    const time = frame / 60;
    motion.update(time, 1 / 60, idleAvatar, options(music(5000 + time * 2)));
  }
  assert.equal(motion.pose, "dance");
  const phase = (motion as unknown as { dancePhase: number }).dancePhase;
  assert.ok(phase > 1.5 && phase < 2.5, String(phase));
});

test("a spin that resumes while the dance blends in never reverses its turn", () => {
  const vrm = emptyRig();
  const motion = new AvatarMotion(vrm, 1.8);
  const phase = () => (motion as unknown as { dancePhase: number }).dancePhase;
  let frame = 0;
  const step = (active: boolean) => {
    const time = frame++ / 60;
    motion.update(time, 1 / 60, idleAvatar, options(music(time * 2, active)));
  };
  // Dance into the spin (style 2) just before its half turn, then pause.
  while (phase() < 22.95) step(true);
  for (let i = 0; i < 120; i++) step(false);
  assert.ok(phase() > 22.9 && phase() < 23, String(phase()));
  let previous = vrm.scene.rotation.y;
  // Resuming crosses turn = π while the dance weight is still small; the old
  // ±π wrap flipped the blended yaw target and turned her backwards.
  for (let i = 0; i < 90; i++) {
    step(true);
    const change = vrm.scene.rotation.y - previous;
    assert.ok(change > -0.002, `frame ${i}: yaw reversed by ${change}`);
    assert.ok(change < 0.2, `frame ${i}: yaw jumped by ${change}`);
    previous = vrm.scene.rotation.y;
  }
  assert.ok(phase() > 23, "the spin passed its half turn");
});
