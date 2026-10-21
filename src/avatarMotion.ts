import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import type { AvatarGesture, AvatarSignal } from "./avatarBehavior.ts";
import { fairyPoses, type V3 } from "./avatarPoses.ts";
import { AvatarArm } from "./avatarArm.ts";

const bones = [
  "hips",
  "spine",
  "chest",
  "neck",
  "head",
  "leftUpperArm",
  "rightUpperArm",
  "leftLowerArm",
  "rightLowerArm",
  "leftHand",
  "rightHand",
  "leftUpperLeg",
  "rightUpperLeg",
  "leftLowerLeg",
  "rightLowerLeg",
  "leftFoot",
  "rightFoot",
] as const;
export class AvatarMotion {
  private vrm: VRM;
  private height: number;
  private nodes = new Map<
    VRMHumanBoneName,
    { node: THREE.Object3D; rest: THREE.Euler }
  >();
  private origin: THREE.Vector3;
  private rotation: THREE.Euler;
  private weights = new Map<string, number>();
  private gaze = new THREE.Object3D();
  private nextBlink = 2 + Math.random() * 3;
  private blinkStart = -10;
  private cue = "";
  private cueStart = 0;
  private energy = 0;
  private arms: { left: AvatarArm; right: AvatarArm };
  private leftGoal: V3 = [0, 0, 0];
  private rightGoal: V3 = [0, 0, 0];
  private wings: {
    node: THREE.Object3D;
    rest: THREE.Quaternion;
    side: number;
    index: number;
  }[] = [];
  private wingTurn = new THREE.Quaternion();
  private wingAxis = new THREE.Vector3(0, 1, 0);
  private wingRoll = new THREE.Quaternion();
  private rollAxis = new THREE.Vector3(0, 0, 1);
  pose: AvatarGesture = "none";
  get wingCount() {
    return this.wings.length;
  }
  constructor(vrm: VRM, height: number) {
    this.vrm = vrm;
    this.height = height;
    this.origin = vrm.scene.position.clone();
    this.rotation = vrm.scene.rotation.clone();
    const bottom =
      new THREE.Box3().setFromObject(vrm.scene).min.y - this.origin.y;
    vrm.scene.traverse((node) => {
      const match = /^(L|R)[ _]wing[ _](\d+)$/i.exec(node.name);
      if (match && (node as THREE.Bone).isBone)
        this.wings.push({
          node,
          rest: node.quaternion.clone(),
          side: match[1].toUpperCase() === "L" ? 1 : -1,
          index: Number(match[2]),
        });
    });
    for (const name of bones) {
      const node = vrm.humanoid.getNormalizedBoneNode(name);
      if (!node) continue;
      if (name === "leftUpperArm") node.rotation.z = -1.1;
      if (name === "rightUpperArm") node.rotation.z = 1.1;
      this.nodes.set(name, { node, rest: node.rotation.clone() });
    }
    this.arms = {
      left: new AvatarArm(vrm, "left", height, bottom),
      right: new AvatarArm(vrm, "right", height, bottom),
    };
    if (vrm.lookAt) vrm.lookAt.target = this.gaze;
  }
  update(
    time: number,
    delta: number,
    signal: AvatarSignal,
    options: {
      motion: boolean;
      gaze: boolean;
      expressions: boolean;
      pointer: { x: number; y: number };
      yaw: number;
      strength?: number;
      still?: boolean;
      demo?: boolean;
    },
  ) {
    const smooth = 1 - Math.exp(-delta * 7);
    const move = options.motion ? 1 : 0;
    const strength = Math.min(1, Math.max(0, options.strength ?? 0.65));
    this.energy = THREE.MathUtils.lerp(
      this.energy,
      signal.energy || 0,
      1 - Math.exp(-delta * 2),
    );
    const vigor = 1 + this.energy * 0.7;
    if (signal.cue !== this.cue) {
      this.cue = signal.cue;
      this.cueStart = time;
    }
    const age = time - this.cueStart;
    const envelope = options.demo
      ? 1
      : THREE.MathUtils.smoothstep(age, 0, 0.45) *
        (1 - THREE.MathUtils.smoothstep(age, 4.5, 6));
    const active =
      options.expressions &&
      signal.gesture !== "none" &&
      (options.demo || age < 6);
    this.pose = !move
      ? "none"
      : active
        ? signal.gesture
        : signal.phase === "thinking"
          ? "think"
          : signal.phase === "listening"
            ? "listen"
            : signal.phase === "speaking"
              ? "explain"
              : "none";
    const pose = fairyPoses[this.pose],
      rest = fairyPoses.none;
    const weight = move * (active ? envelope : 1);
    const talk = signal.phase === "speaking" ? 1 : 0;
    const lookX = options.gaze ? options.pointer.x : 0,
      lookY = options.gaze ? options.pointer.y : 0;
    const glance = Math.sin(time * 0.48) * Math.sin(time * 0.19) * move;
    const breath = Math.sin(time * 1.7) * move;
    const bob = Math.sin(time * (1.35 + this.energy * 0.3));
    const nod = this.pose === "nod" ? Math.sin(age * 5) * 0.06 * weight : 0;
    for (const [name, { node, rest: rotation }] of this.nodes) {
      if (/Arm|Hand/.test(name) && move) continue;
      let x = 0,
        y = 0,
        z = 0;
      if (name === "hips") {
        x = pose.body[0] * weight;
        y = pose.body[1] * weight;
        z = pose.body[2] * weight;
      }
      if (name === "spine") {
        x = breath * 0.014;
        z = Math.sin(time * 0.65) * 0.025 * move * vigor;
      }
      if (name === "chest") x = breath * 0.012;
      if (name === "neck") {
        x = nod;
        z = pose.head[2] * weight * 0.35;
      }
      if (name === "head") {
        x = lookY * 0.16 + pose.head[0] * weight;
        y = lookX * 0.28 + glance * 0.07 + pose.head[1] * weight;
        z = pose.head[2] * weight * 0.65;
      }
      if (name === "leftUpperLeg" || name === "rightUpperLeg") {
        const leg = name === "leftUpperLeg" ? pose.leftLeg : pose.rightLeg;
        x = leg[0] * move;
        y = leg[1] * move;
        z = leg[2] * move;
      }
      if (name === "leftLowerLeg" || name === "rightLowerLeg")
        x = (pose.knees[name === "leftLowerLeg" ? 0 : 1] + bob * 0.04) * move;
      if (name === "leftFoot" || name === "rightFoot") x = -0.18 * move;
      node.rotation.x = THREE.MathUtils.lerp(
        node.rotation.x,
        rotation.x + x,
        smooth,
      );
      node.rotation.y = THREE.MathUtils.lerp(
        node.rotation.y,
        rotation.y + y,
        smooth,
      );
      node.rotation.z = THREE.MathUtils.lerp(
        node.rotation.z,
        rotation.z + z,
        smooth,
      );
    }
    this.vrm.scene.position.set(
      this.origin.x +
        Math.sin(time * 0.43) * this.height * 0.009 * move * vigor,
      this.origin.y + (0.025 + bob * 0.017 * vigor) * this.height * move,
      this.origin.z + Math.sin(time * 0.39) * this.height * 0.018 * move,
    );
    this.vrm.scene.rotation.y = THREE.MathUtils.lerp(
      this.vrm.scene.rotation.y,
      this.rotation.y +
        options.yaw +
        Math.sin(time * 0.35) * 0.035 * move * vigor,
      smooth,
    );
    this.vrm.scene.updateMatrixWorld(true);
    if (move) {
      for (let i = 0; i < 3; i++) {
        this.leftGoal[i] = THREE.MathUtils.lerp(
          rest.left[i],
          pose.left[i],
          weight,
        );
        this.rightGoal[i] = THREE.MathUtils.lerp(
          rest.right[i],
          pose.right[i],
          weight,
        );
      }
      const flourish =
        this.pose === "wave"
          ? Math.sin(age * 7) * 0.018
          : this.pose === "explain"
            ? Math.sin(time * 2.2) * 0.009 * vigor
            : 0;
      this.arms.left.update(
        this.leftGoal,
        pose.leftWrist,
        pose.leftHand,
        smooth,
        breath * 0.002,
      );
      this.arms.right.update(
        this.rightGoal,
        pose.rightWrist,
        pose.rightHand,
        smooth,
        flourish * weight + breath * 0.002,
      );
    }
    if (!move) {
      this.arms.left.reset(smooth);
      this.arms.right.reset(smooth);
    }
    const head = this.nodes.get("head")?.node;
    const headPosition = head?.getWorldPosition(this.gaze.position);
    this.gaze.position.set(
      (headPosition?.x || this.origin.x) +
        (lookX * 0.9 + glance * 0.2) * this.height,
      (headPosition?.y || this.origin.y + this.height * 0.85) +
        (0.04 - lookY * 0.5) * this.height,
      this.origin.z + this.height * 1.1,
    );
    const cycle = time % (8.5 - this.energy * 3),
      burst = cycle < 2 ? Math.sin((cycle / 2) * Math.PI) ** 2 : 0;
    for (const wing of this.wings) {
      const flap =
        Math.sin(time * (10 + this.energy * 3) + wing.index * 0.3) *
        (0.2 + this.energy * 0.14) *
        burst;
      const angle =
        (Math.sin(time * 1.5 + wing.index * 0.3) * 0.025 + flap) *
        wing.side *
        move;
      wing.node.quaternion
        .copy(wing.rest)
        .multiply(this.wingTurn.setFromAxisAngle(this.wingAxis, angle))
        .multiply(this.wingRoll.setFromAxisAngle(this.rollAxis, -angle * 0.2));
    }
    if (time >= this.nextBlink) {
      this.blinkStart = time;
      this.nextBlink = time + 3 + Math.random() * 4;
    }
    const blinkAge = time - this.blinkStart;
    const targets: Record<string, number> = {
      blink:
        !options.still && blinkAge >= 0 && blinkAge < 0.18
          ? Math.sin((blinkAge / 0.18) * Math.PI) ** 2
          : this.pose === "tired"
            ? 0.3
            : 0,
      blinkLeft: this.pose === "thumbsup" ? 0.9 : 0,
      blinkRight: 0,
      aa: talk ? 0.1 + Math.abs(Math.sin(time * 9)) * 0.4 : 0,
      ou: talk ? Math.max(0, Math.sin(time * 5.3)) * 0.12 : 0,
      happy:
        signal.emotion === "happy"
          ? strength * (this.pose === "thumbsup" ? 0.5 : 1)
          : 0,
      sad: signal.emotion === "sad" ? strength * (options.demo ? 1 : 0.9) : 0,
      angry: signal.emotion === "angry" ? strength : 0,
      relaxed:
        signal.emotion === "relaxed" ? strength * (options.demo ? 1 : 0.8) : 0,
      surprised:
        signal.emotion === "surprised"
          ? strength * (options.demo ? 1 : 0.8)
          : 0,
    };
    for (const [name, value] of Object.entries(targets)) {
      if (!this.vrm.expressionManager?.getExpression(name)) continue;
      const target =
        options.expressions || ["blink", "aa", "ou"].includes(name) ? value : 0;
      const weight =
        name === "blink" || (talk === 0 && ["aa", "ou"].includes(name))
          ? target
          : THREE.MathUtils.lerp(this.weights.get(name) || 0, target, smooth);
      this.weights.set(name, weight);
      this.vrm.expressionManager.setValue(name, weight);
    }
    this.vrm.update(delta);
  }
}
