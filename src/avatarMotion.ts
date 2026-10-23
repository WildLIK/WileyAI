import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import type { AvatarGesture, AvatarSignal } from "./avatarBehavior.ts";
import { fairyPoses, type V3 } from "./avatarPoses.ts";
import { AvatarArm } from "./avatarArm.ts";
import { dancePose, type DanceStyle } from "./avatarDance.ts";
import type { MusicPulse } from "./avatarMusic.ts";

const bones = [
  "hips",
  "spine",
  "chest",
  "leftShoulder",
  "rightShoulder",
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
  private danceWeight = 0;
  private dancePhase = 0;
  petWeight = 0;
  blush = 0;
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
      music?: MusicPulse;
      pet?: number;
    },
  ) {
    const smooth = 1 - Math.exp(-delta * 7);
    this.petWeight = THREE.MathUtils.lerp(
      this.petWeight,
      options.pet || 0,
      smooth,
    );
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
      if (options.demo && signal.gesture.startsWith("dance"))
        this.dancePhase = 0;
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
    const dancing =
      this.petWeight < 0.1 &&
      move &&
      (this.pose.startsWith("dance") ||
        (!options.demo &&
          options.music?.active &&
          signal.phase === "idle" &&
          !active));
    this.danceWeight = !move
      ? 0
      : THREE.MathUtils.lerp(this.danceWeight, dancing ? 1 : 0, smooth);
    if (dancing)
      this.dancePhase = options.music?.active
        ? THREE.MathUtils.lerp(
            this.dancePhase + delta * ((options.music.bpm || 120) / 60),
            options.music.phase,
            smooth * 0.5,
          )
        : this.dancePhase + delta * 2;
    const style: DanceStyle = options.demo
      ? this.pose === "dance2"
        ? 2
        : this.pose === "dance3"
          ? 3
          : 1
      : (((Math.floor(this.dancePhase / 16) % 3) + 1) as DanceStyle);
    const dance = dancePose(this.dancePhase, style);
    const basePose = fairyPoses[this.pose];
    const blend = (a: V3, b: V3): V3 =>
      a.map((value, i) =>
        THREE.MathUtils.lerp(value, b[i], this.danceWeight),
      ) as V3;
    const pose =
        this.danceWeight > 0.001
          ? {
              ...basePose,
              left: blend(basePose.left, dance.left),
              right: blend(basePose.right, dance.right),
              leftWrist: blend(basePose.leftWrist, dance.leftWrist),
              rightWrist: blend(basePose.rightWrist, dance.rightWrist),
              // Automatic music starts from idle; its folded palms and
              // elbow poles must not constrain the dance's wider reach.
              leftElbow: dance.leftElbow,
              rightElbow: dance.rightElbow,
              leftPalm: dance.leftPalm,
              rightPalm: dance.rightPalm,
              leftHand:
                this.danceWeight > 0.5 ? dance.leftHand : basePose.leftHand,
              rightHand:
                this.danceWeight > 0.5 ? dance.rightHand : basePose.rightHand,
              head: blend(basePose.head, dance.head),
              body: blend(basePose.body, dance.body),
              leftLeg: blend(basePose.leftLeg, dance.leftLeg),
              rightLeg: blend(basePose.rightLeg, dance.rightLeg),
              knees: basePose.knees.map((value, i) =>
                THREE.MathUtils.lerp(value, dance.knees[i], this.danceWeight),
              ) as [number, number],
            }
          : basePose,
      rest = fairyPoses.none;
    if (this.danceWeight > 0.1)
      this.pose = style === 2 ? "dance2" : style === 3 ? "dance3" : "dance";
    const weight = move * (active ? envelope : 1);
    const talk = signal.phase === "speaking" ? 1 : 0;
    const lookX = options.gaze ? options.pointer.x : 0,
      lookY = options.gaze ? options.pointer.y : 0;
    const glance = Math.sin(time * 0.48) * Math.sin(time * 0.19) * move;
    const breath = Math.sin(time * 1.7) * move;
    const accent =
      (options.music?.beat ||
        (options.demo && this.pose.startsWith("dance")
          ? Math.max(0, Math.cos(this.dancePhase * Math.PI * 2))
          : 0)) * this.danceWeight;
    const bob = Math.sin(time * (1.35 + this.energy * 0.3)) + accent * 0.6;
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
      if (name === "chest") x = breath * 0.012 + this.petWeight * 0.1;
      if (name === "leftShoulder" || name === "rightShoulder")
        z =
          this.pose === "shy"
            ? (name === "leftShoulder" ? 0.1 : -0.1) * weight
            : 0;
      if (name === "neck") {
        x = nod;
        z = pose.head[2] * weight * 0.35;
      }
      if (name === "head") {
        x = lookY * 0.26 + pose.head[0] * weight;
        y = lookX * 0.48 + glance * 0.07 + pose.head[1] * weight;
        z = pose.head[2] * weight * 0.65;
        // A small bow and tilt lean into the hand without interrupting speech.
        x = THREE.MathUtils.lerp(x, 0.19, this.petWeight);
        y *= 1 - this.petWeight * 0.8;
        z = THREE.MathUtils.lerp(
          z,
          -0.13 + options.pointer.x * 0.08,
          this.petWeight,
        );
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
        (Math.sin(time * 0.43) * 0.009 * move * vigor +
          (dance.shift?.[0] || 0) * this.danceWeight) *
          this.height,
      this.origin.y +
        (0.025 +
          bob * 0.017 * vigor +
          (dance.shift?.[1] || 0) * this.danceWeight) *
          this.height *
          move,
      this.origin.z + Math.sin(time * 0.39) * this.height * 0.018 * move,
    );
    const danceTurn =
      Math.atan2(Math.sin(dance.turn || 0), Math.cos(dance.turn || 0)) *
      this.danceWeight;
    const targetYaw =
      this.rotation.y +
      options.yaw +
      Math.sin(time * 0.35) * 0.035 * move * vigor +
      danceTurn;
    const yawDelta = Math.atan2(
      Math.sin(targetYaw - this.vrm.scene.rotation.y),
      Math.cos(targetYaw - this.vrm.scene.rotation.y),
    );
    this.vrm.scene.rotation.y += yawDelta * smooth;
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
        pose.leftElbow,
        pose.leftPalm,
      );
      this.arms.right.update(
        this.rightGoal,
        pose.rightWrist,
        pose.rightHand,
        smooth,
        flourish * weight + breath * 0.002,
        pose.rightElbow,
        pose.rightPalm,
      );
    }
    if (!move) {
      // Reduced motion keeps the same composed idle silhouette. Apply it
      // without oscillation instead of dropping the arms into the bind pose.
      for (const side of ["left", "right"] as const)
        this.arms[side].update(
          rest[side],
          rest[`${side}Wrist`],
          rest[`${side}Hand`],
          1,
          0,
          rest[`${side}Elbow`],
          rest[`${side}Palm`],
        );
    }
    const head = this.nodes.get("head")?.node;
    const headPosition = head?.getWorldPosition(this.gaze.position);
    this.gaze.position.set(
      (headPosition?.x || this.origin.x) +
        (lookX * 0.9 + glance * 0.2) * this.height,
      (headPosition?.y || this.origin.y + this.height * 0.85) +
        ((this.pose === "think" ? 0.18 : 0.04) - lookY * 0.5) * this.height,
      this.origin.z + this.height * 1.1,
    );
    const cycle = time % (8.5 - this.energy * 3),
      burst = cycle < 2 ? Math.sin((cycle / 2) * Math.PI) ** 2 : 0;
    for (const wing of this.wings) {
      const flap =
        Math.sin(time * (10 + this.energy * 3) + wing.index * 0.3) *
        (0.2 + this.energy * 0.14) *
        Math.max(burst, this.danceWeight * (0.4 + accent * 0.6));
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
        this.petWeight > 0.05
          ? Math.max(
              this.petWeight * 0.7,
              signal.emotion === "happy" ? strength : 0,
            )
          : signal.emotion === "happy" ||
              (dancing && signal.emotion === "neutral")
            ? strength * (this.pose === "thumbsup" ? 0.5 : 1)
            : 0,
      sad:
        signal.emotion === "sad"
          ? strength * (options.demo ? 1 : 0.9) * (1 - this.petWeight)
          : 0,
      angry: signal.emotion === "angry" ? strength * (1 - this.petWeight) : 0,
      relaxed:
        signal.emotion === "relaxed" ? strength * (options.demo ? 1 : 0.8) : 0,
      surprised:
        signal.emotion === "surprised"
          ? strength * (options.demo ? 1 : 0.8)
          : 0,
      blush: Math.max(
        this.petWeight * 0.8,
        this.pose === "shy"
          ? strength * 0.65
          : signal.emotion === "happy" || signal.emotion === "relaxed"
            ? strength * 0.4
            : 0,
      ),
      // Cloth follows the actual blended leg rotations, independently of
      // facial-expression settings. Ordinary VRMs simply lack these morphs.
      skirtRaiseLeft: THREE.MathUtils.clamp(
        -(this.nodes.get("leftUpperLeg")?.node.rotation.x || 0) / 1.1,
        0,
        1,
      ),
      skirtRaiseRight: THREE.MathUtils.clamp(
        -(this.nodes.get("rightUpperLeg")?.node.rotation.x || 0) / 1.1,
        0,
        1,
      ),
    };
    for (const [name, value] of Object.entries(targets)) {
      if (!this.vrm.expressionManager?.getExpression(name)) continue;
      const target =
        options.expressions ||
        ["blink", "aa", "ou"].includes(name) ||
        name.startsWith("skirtRaise")
          ? value
          : 0;
      const weight =
        name === "blink" ||
        name.startsWith("skirtRaise") ||
        (talk === 0 && ["aa", "ou"].includes(name))
          ? target
          : THREE.MathUtils.lerp(this.weights.get(name) || 0, target, smooth);
      this.weights.set(name, weight);
      this.vrm.expressionManager.setValue(name, weight);
    }
    this.blush = this.weights.get("blush") || 0;
    this.vrm.update(delta);
  }
}
