import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import type { HandShape, V3 } from "./avatarPoses";

/** Analytic two-bone reach on the VRM normalized rig; no changes to the file. */
export class AvatarArm {
  private vrm: VRM;
  private side: "left" | "right";
  private height: number;
  private bottom: number;
  private upper;
  private lower;
  private hand;
  private a = new THREE.Vector3();
  private b = new THREE.Vector3();
  private c = new THREE.Vector3();
  private target = new THREE.Vector3();
  private pole = new THREE.Vector3();
  private direction = new THREE.Vector3();
  private elbow = new THREE.Vector3();
  private from = new THREE.Vector3();
  private to = new THREE.Vector3();
  private delta = new THREE.Quaternion();
  private world = new THREE.Quaternion();
  private parent = new THREE.Quaternion();
  private oldUpper = new THREE.Quaternion();
  private oldLower = new THREE.Quaternion();
  private fingers: {
    node: THREE.Object3D;
    rest: THREE.Euler;
    thumb: boolean;
    index: boolean;
    joint: number;
  }[] = [];
  constructor(
    vrm: VRM,
    side: "left" | "right",
    height: number,
    bottom: number,
  ) {
    this.vrm = vrm;
    this.side = side;
    this.height = height;
    this.bottom = bottom;
    this.upper = vrm.humanoid.getNormalizedBoneNode(`${side}UpperArm`);
    this.lower = vrm.humanoid.getNormalizedBoneNode(`${side}LowerArm`);
    this.hand = vrm.humanoid.getNormalizedBoneNode(`${side}Hand`);
    for (const digit of ["Thumb", "Index", "Middle", "Ring", "Little"] as const)
      for (const [joint, segment] of (digit === "Thumb"
        ? ["Metacarpal", "Proximal", "Distal"]
        : ["Proximal", "Intermediate", "Distal"]
      ).entries()) {
        const node = vrm.humanoid.getNormalizedBoneNode(
          `${side}${digit}${segment}` as Parameters<
            typeof vrm.humanoid.getNormalizedBoneNode
          >[0],
        );
        if (node)
          this.fingers.push({
            node,
            rest: node.rotation.clone(),
            thumb: digit === "Thumb",
            index: digit === "Index",
            joint,
          });
      }
  }
  private turn(node: THREE.Object3D, from: THREE.Vector3, to: THREE.Vector3) {
    this.delta.setFromUnitVectors(from.normalize(), to.normalize());
    node.getWorldQuaternion(this.world);
    if (node.parent) node.parent.getWorldQuaternion(this.parent).invert();
    else this.parent.identity();
    node.quaternion.copy(this.parent.multiply(this.delta.multiply(this.world)));
    node.updateWorldMatrix(false, true);
  }
  reset(smooth: number) {
    for (const finger of this.fingers)
      finger.node.rotation.z = THREE.MathUtils.lerp(
        finger.node.rotation.z,
        finger.rest.z,
        smooth,
      );
  }
  update(
    goal: V3,
    wrist: V3,
    shape: HandShape,
    smooth: number,
    flutter: number,
  ) {
    if (!this.upper || !this.lower || !this.hand) return;
    const sign = this.side === "left" ? 1 : -1;
    const scene = this.vrm.scene;
    this.upper.updateWorldMatrix(true, true);
    this.upper.getWorldPosition(this.a);
    this.lower.getWorldPosition(this.b);
    this.hand.getWorldPosition(this.c);
    const upperLength = this.a.distanceTo(this.b),
      lowerLength = this.b.distanceTo(this.c);
    if (upperLength < 0.0001 || lowerLength < 0.0001) return;
    this.target.set(
      goal[0] * this.height,
      this.bottom + (goal[1] + flutter) * this.height,
      goal[2] * this.height,
    );
    scene.localToWorld(this.target);
    this.direction.copy(this.target).sub(this.a);
    const distance = THREE.MathUtils.clamp(
      this.direction.length(),
      Math.abs(upperLength - lowerLength) + 0.001,
      (upperLength + lowerLength) * 0.98,
    );
    this.direction.normalize();
    this.target.copy(this.a).addScaledVector(this.direction, distance);
    this.pole.set(
      sign * this.height * 0.36,
      this.bottom + this.height * 0.62,
      this.height * 0.18,
    );
    scene.localToWorld(this.pole);
    this.pole.sub(this.a);
    this.pole.addScaledVector(this.direction, -this.pole.dot(this.direction));
    if (this.pole.lengthSq() < 1e-8)
      this.pole.set(0, 0, 1).addScaledVector(this.direction, -this.direction.z);
    this.pole.normalize();
    const along =
      (upperLength * upperLength -
        lowerLength * lowerLength +
        distance * distance) /
      (2 * distance);
    this.elbow
      .copy(this.a)
      .addScaledVector(this.direction, along)
      .addScaledVector(
        this.pole,
        Math.sqrt(Math.max(0, upperLength * upperLength - along * along)),
      );
    this.oldUpper.copy(this.upper.quaternion);
    this.oldLower.copy(this.lower.quaternion);
    this.turn(
      this.upper,
      this.from.copy(this.b).sub(this.a),
      this.to.copy(this.elbow).sub(this.a),
    );
    this.lower.getWorldPosition(this.b);
    this.hand.getWorldPosition(this.c);
    this.turn(
      this.lower,
      this.from.copy(this.c).sub(this.b),
      this.to.copy(this.target).sub(this.b),
    );
    this.upper.quaternion.slerp(this.oldUpper, 1 - smooth);
    this.lower.quaternion.slerp(this.oldLower, 1 - smooth);
    this.hand.rotation.x = THREE.MathUtils.lerp(
      this.hand.rotation.x,
      wrist[0],
      smooth,
    );
    this.hand.rotation.y = THREE.MathUtils.lerp(
      this.hand.rotation.y,
      wrist[1],
      smooth,
    );
    this.hand.rotation.z = THREE.MathUtils.lerp(
      this.hand.rotation.z,
      wrist[2],
      smooth,
    );
    for (const finger of this.fingers) {
      let curl = shape === "soft" ? 0.18 : shape === "open" ? 0.02 : 0.95;
      if (
        (shape === "point" && finger.index) ||
        (shape === "thumbsup" && finger.thumb)
      )
        curl = 0;
      if (finger.thumb) curl *= 0.45;
      finger.node.rotation.z = THREE.MathUtils.lerp(
        finger.node.rotation.z,
        finger.rest.z - sign * curl * (finger.joint === 0 ? 1 : 0.8),
        smooth,
      );
    }
  }
}
