import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import type { AvatarGesture, AvatarSignal } from "./avatarBehavior.ts";
import { fairyPoses, type V3 } from "./avatarPoses.ts";
import { AvatarArm } from "./avatarArm.ts";
import {
  danceStyle,
  dancePose,
  followBeat,
  type DanceStyle,
} from "./avatarDance.ts";
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
const sides = ["left", "right"] as const;
const expressions = [
  "blink",
  "blinkLeft",
  "blinkRight",
  "aa",
  "ou",
  "happy",
  "sad",
  "angry",
  "relaxed",
  "surprised",
  "blush",
  "skirtRaiseLeft",
  "skirtRaiseRight",
] as const;
type Expression = (typeof expressions)[number];
// Blinks, the mouth and cloth ignore the facial-expression setting.
const automatic = expressions.map(
  (name) =>
    name === "blink" ||
    name === "aa" ||
    name === "ou" ||
    name.startsWith("skirtRaise"),
);
const mouth = expressions.map((name) => name === "aa" || name === "ou");
const instant = expressions.map(
  (name) => name === "blink" || name.startsWith("skirtRaise"),
);

/**
 * VRM 0.x normalized rigs keep the file's -Z facing; VRMUtils.rotateVRM0 turns
 * the whole scene by π instead. The same visible motion therefore needs the
 * opposite X and Z rotation/offset components (the three-vrm VRMA loader flips
 * them the same way). Returns 1 for VRM 1.0, so its math stays bit-identical.
 */
export function vrmFacing(vrm: { meta?: unknown }): 1 | -1 {
  return (vrm.meta as { metaVersion?: string } | undefined)?.metaVersion === "0"
    ? -1
    : 1;
}

/** Mirror a VRM 1.0 Euler/offset triple into the rig's own frame. */
export function facingV3(value: V3, facing: number, out: V3 = [0, 0, 0]): V3 {
  out[0] = value[0] * facing;
  out[1] = value[1];
  out[2] = value[2] * facing;
  return out;
}

/**
 * Bones that can visibly move geometry: any bone with a non-zero skin weight.
 * Spring joints whose bones and descendants are absent from this set (and
 * carry no rendered object) only cost simulation time.
 */
export function influentialBones(root: THREE.Object3D) {
  const used = new Set<THREE.Object3D>();
  root.traverse((object) => {
    const mesh = object as THREE.SkinnedMesh;
    if (!mesh.isSkinnedMesh || !mesh.skeleton) return;
    const index = mesh.geometry.getAttribute("skinIndex"),
      weight = mesh.geometry.getAttribute("skinWeight");
    if (!index || !weight) return;
    const skin = mesh.skeleton.bones;
    for (let vertex = 0; vertex < index.count; vertex++)
      for (let k = 0; k < index.itemSize; k++)
        if (weight.getComponent(vertex, k) > 0) {
          const bone = skin[index.getComponent(vertex, k)];
          if (bone) used.add(bone);
        }
  });
  return used;
}

/** Removes spring joints that cannot move any vertex; returns their count. */
export function pruneSpringBones(vrm: VRM) {
  const manager = vrm.springBoneManager;
  if (!manager || manager.joints.size === 0) return 0;
  const used = influentialBones(vrm.scene);
  // A node constraint may copy a spring bone onto a weighted node.
  for (const constraint of vrm.nodeConstraintManager?.constraints ?? [])
    used.add(constraint.source);
  const visible = new Map<THREE.Object3D, boolean>();
  const moves = (bone: THREE.Object3D) => {
    let result = visible.get(bone);
    if (result === undefined) {
      let found = false;
      bone.traverse((object) => {
        const shown = object as THREE.Object3D & {
          isMesh?: boolean;
          isLine?: boolean;
          isPoints?: boolean;
          isSprite?: boolean;
        };
        if (
          used.has(object) ||
          shown.isMesh ||
          shown.isLine ||
          shown.isPoints ||
          shown.isSprite
        )
          found = true;
      });
      visible.set(bone, (result = found));
    }
    return result;
  };
  let removed = 0;
  for (const joint of [...manager.joints])
    if (!moves(joint.bone)) {
      manager.deleteJoint(joint);
      // Joints take over their bone's matrix; give it back to three.js.
      joint.bone.matrixAutoUpdate = true;
      removed++;
    }
  return removed;
}

export class AvatarMotion {
  private vrm: VRM;
  private height: number;
  private nodes = new Map<
    VRMHumanBoneName,
    { node: THREE.Object3D; rest: THREE.Euler; limb: boolean }
  >();
  private facing: 1 | -1;
  private moving = true;
  private livelyUntil = 0;
  private emotion = "";
  private targets = {} as Record<Expression, number>;
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
  /** True while anything beyond the slow idle loop moves or settles. */
  lively = true;
  get wingCount() {
    return this.wings.length;
  }
  constructor(vrm: VRM, height: number) {
    this.vrm = vrm;
    this.height = height;
    this.facing = vrmFacing(vrm);
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
      if (name === "leftUpperArm") node.rotation.z = -1.1 * this.facing;
      if (name === "rightUpperArm") node.rotation.z = 1.1 * this.facing;
      // Yaw first, then pitch around the turned head: a natural look order.
      if (name === "head") node.rotation.order = "YXZ";
      this.nodes.set(name, {
        node,
        rest: node.rotation.clone(),
        limb: /Arm|Hand/.test(name),
      });
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
    /** Apply the target pose at once, e.g. for the first frame after loading. */
    snap = false,
  ) {
    const smooth = snap ? 1 : 1 - Math.exp(-delta * 7);
    const facing = this.facing;
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
    if (!dancing && this.danceWeight < 0.001) this.danceWeight = 0;
    if (dancing)
      this.dancePhase = options.music?.active
        ? followBeat(
            this.dancePhase,
            options.music.phase,
            delta,
            options.music.bpm || 120,
            smooth,
          )
        : this.dancePhase + delta * 2;
    const style: DanceStyle = options.demo
      ? this.pose === "dance2"
        ? 2
        : this.pose === "dance3"
          ? 3
          : 1
      : danceStyle(this.dancePhase);
    const dance =
      this.danceWeight > 0 ? dancePose(this.dancePhase, style) : undefined;
    const basePose = fairyPoses[this.pose];
    const blend = (a: V3, b: V3): V3 =>
      a.map((value, i) =>
        THREE.MathUtils.lerp(value, b[i], this.danceWeight),
      ) as V3;
    const pose =
        dance && this.danceWeight > 0.001
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
              // Deeply folded knees read as running in the air; keep the
              // rhythm in the legs with three quarters of the bend.
              knees: basePose.knees.map((value, i) =>
                THREE.MathUtils.lerp(
                  value,
                  dance.knees[i] * 0.75,
                  this.danceWeight,
                ),
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
    for (const [name, { node, rest: rotation, limb }] of this.nodes) {
      if (limb && move) continue;
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
            ? (name === "leftShoulder" ? 0.17 : -0.17) * weight
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
      // Pointed toes, as a levitating fairy holds them in the reference art.
      if (name === "leftFoot" || name === "rightFoot") x = 0.45 * move;
      node.rotation.x = THREE.MathUtils.lerp(
        node.rotation.x,
        rotation.x + x * facing,
        smooth,
      );
      node.rotation.y = THREE.MathUtils.lerp(
        node.rotation.y,
        rotation.y + y,
        smooth,
      );
      node.rotation.z = THREE.MathUtils.lerp(
        node.rotation.z,
        rotation.z + z * facing,
        smooth,
      );
    }
    this.vrm.scene.position.set(
      this.origin.x +
        (Math.sin(time * 0.43) * 0.009 * move * vigor +
          (dance?.shift?.[0] || 0) * this.danceWeight) *
          this.height,
      this.origin.y +
        (0.025 +
          bob * 0.017 * vigor +
          (dance?.shift?.[1] || 0) * this.danceWeight) *
          this.height *
          move,
      this.origin.z + Math.sin(time * 0.39) * this.height * 0.018 * move,
    );
    // The turn runs 0..2π within a cycle and is exactly a full turn at its
    // end, so scaling it stays continuous while the dance blends in or out.
    // Wrapping it to ±π first jumped by 2π·weight halfway through a spin.
    const danceTurn = (dance?.turn || 0) * this.danceWeight;
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
    // No scene-wide matrix update here: the arm chain and the head refresh
    // their own ancestors before reading world transforms.
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
      if (this.pose === "wave")
        // The palm sways side to side; a wave that only bobs looks frozen.
        this.rightGoal[0] += Math.sin(age * 7) * 0.035 * weight;
      if (this.pose === "explain") {
        // Unhurried beat gestures while talking, never in step between hands.
        const amount = weight * vigor;
        this.rightGoal[0] += Math.sin(time * 1.9) * 0.022 * amount;
        this.rightGoal[2] += Math.cos(time * 1.4) * 0.02 * amount;
        this.leftGoal[0] -= Math.sin(time * 1.55 + 1.3) * 0.018 * amount;
        this.leftGoal[1] += Math.sin(time * 2.3 + 2.1) * 0.012 * amount;
      }
      const firm = pose.straightArms ? weight : 0;
      this.arms.left.update(
        this.leftGoal,
        pose.leftWrist,
        pose.leftHand,
        smooth,
        breath * 0.002,
        pose.leftElbow,
        pose.leftPalm,
        firm,
      );
      this.arms.right.update(
        this.rightGoal,
        pose.rightWrist,
        pose.rightHand,
        smooth,
        flourish * weight + breath * 0.002,
        pose.rightElbow,
        pose.rightPalm,
        firm,
      );
    }
    if (!move) {
      // Reduced motion keeps the same composed idle silhouette. Apply it
      // without oscillation instead of dropping the arms into the bind pose.
      for (const side of sides)
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
    const targets = this.targets;
    targets.blink =
      !options.still && blinkAge >= 0 && blinkAge < 0.18
        ? Math.sin((blinkAge / 0.18) * Math.PI) ** 2
        : this.pose === "tired"
          ? 0.3
          : 0;
    targets.blinkLeft = this.pose === "thumbsup" ? 0.9 : 0;
    targets.blinkRight = 0;
    targets.aa = talk ? 0.1 + Math.abs(Math.sin(time * 9)) * 0.4 : 0;
    targets.ou = talk ? Math.max(0, Math.sin(time * 5.3)) * 0.12 : 0;
    targets.happy =
      this.petWeight > 0.05
        ? Math.max(
            this.petWeight * 0.7,
            signal.emotion === "happy" ? strength : 0,
          )
        : signal.emotion === "happy" ||
            (dancing && signal.emotion === "neutral")
          ? strength * (this.pose === "thumbsup" ? 0.5 : 1)
          : 0;
    targets.sad =
      signal.emotion === "sad"
        ? strength * (options.demo ? 1 : 0.9) * (1 - this.petWeight)
        : 0;
    targets.angry =
      signal.emotion === "angry" ? strength * (1 - this.petWeight) : 0;
    targets.relaxed =
      signal.emotion === "relaxed" ? strength * (options.demo ? 1 : 0.8) : 0;
    targets.surprised =
      signal.emotion === "surprised" ? strength * (options.demo ? 1 : 0.8) : 0;
    if (this.pose === "shy") {
      // Reference shy face: eyes open and looking up, a deep blush and
      // slightly worried brows, not the squint of a broad smile.
      targets.happy = Math.min(targets.happy, strength * 0.25);
      targets.relaxed = Math.min(targets.relaxed, strength * 0.4);
      targets.sad = Math.max(targets.sad, strength * 0.22 * weight);
    }
    targets.blush = Math.max(
      this.petWeight * 0.8,
      this.pose === "shy"
        ? Math.min(1, strength * 1.3)
        : signal.emotion === "happy" || signal.emotion === "relaxed"
          ? strength * 0.4
          : 0,
    );
    // Cloth follows the actual blended leg rotations, independently of
    // facial-expression settings. Ordinary VRMs simply lack these morphs.
    targets.skirtRaiseLeft = THREE.MathUtils.clamp(
      -((this.nodes.get("leftUpperLeg")?.node.rotation.x || 0) * facing) / 1.1,
      0,
      1,
    );
    targets.skirtRaiseRight = THREE.MathUtils.clamp(
      -((this.nodes.get("rightUpperLeg")?.node.rotation.x || 0) * facing) / 1.1,
      0,
      1,
    );
    for (let i = 0; i < expressions.length; i++) {
      const name = expressions[i];
      if (!this.vrm.expressionManager?.getExpression(name)) continue;
      const target = options.expressions || automatic[i] ? targets[name] : 0;
      const weight =
        instant[i] || (talk === 0 && mouth[i])
          ? target
          : THREE.MathUtils.lerp(this.weights.get(name) || 0, target, smooth);
      this.weights.set(name, weight);
      this.vrm.expressionManager.setValue(name, weight);
    }
    this.blush = this.weights.get("blush") || 0;
    if (
      (signal.cue !== "" && age < 1.5) ||
      signal.emotion !== this.emotion ||
      signal.phase !== "idle" ||
      this.pose !== "none" ||
      this.danceWeight > 0.01 ||
      this.petWeight > 0.01
    )
      this.livelyUntil = time + 1.5;
    this.emotion = signal.emotion;
    this.lively = time < this.livelyUntil;
    this.vrm.update(delta);
    if (this.moving && !move) {
      // Reduced motion drops the hover and dance in one frame. Restart hair
      // and cloth from rest instead of letting them whip after the jump.
      this.vrm.scene.updateMatrixWorld(true);
      this.vrm.springBoneManager?.reset();
    }
    this.moving = Boolean(move);
  }
}
