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
  private to = new THREE.Vector3();
  private delta = new THREE.Quaternion();
  private world = new THREE.Quaternion();
  private parent = new THREE.Quaternion();
  private oldUpper = new THREE.Quaternion();
  private oldLower = new THREE.Quaternion();
  private palm = new THREE.Quaternion();
  private palmEuler = new THREE.Euler();
  private sceneRotation = new THREE.Quaternion();
  private sceneInverse = new THREE.Quaternion();
  private twist = new THREE.Quaternion();
  private swing = new THREE.Quaternion();
  private fingerTarget = new THREE.Quaternion();
  private fingerEuler = new THREE.Euler();
  private basis = new THREE.Matrix4();
  private axis = new THREE.Vector3();
  private thumbUp = new THREE.Vector3();
  private palmUp = new THREE.Vector3();
  private handRest = new THREE.Quaternion();
  private hingeNormal = new THREE.Vector3();
  private hingeAxis = new THREE.Vector3();
  private hingeCurrent = new THREE.Vector3();
  private hingeDesired = new THREE.Vector3();
  private hingeCross = new THREE.Vector3();
  private hingeRoll = new THREE.Quaternion();
  private aims = new Map<
    THREE.Object3D,
    { direction: THREE.Vector3; rotation: THREE.Quaternion }
  >();
  private fingers: {
    node: THREE.Object3D;
    rest: THREE.Quaternion;
    thumb: boolean;
    index: boolean;
    joint: number;
    digit: number;
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
    if (this.upper && this.lower && this.hand) {
      vrm.scene.updateMatrixWorld(true);
      vrm.scene.getWorldQuaternion(this.sceneRotation);
      this.sceneInverse.copy(this.sceneRotation).invert();
      this.handRest.copy(this.hand.quaternion);
      for (const [node, child] of [
        [this.upper, this.lower],
        [this.lower, this.hand],
      ]) {
        const origin = node.getWorldPosition(new THREE.Vector3());
        const direction = child
          .getWorldPosition(new THREE.Vector3())
          .sub(origin)
          .applyQuaternion(this.sceneInverse)
          .normalize();
        const rotation = node
          .getWorldQuaternion(new THREE.Quaternion())
          .premultiply(this.sceneInverse);
        this.aims.set(node, { direction, rotation });
      }
    }
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
            rest: node.quaternion.clone(),
            thumb: digit === "Thumb",
            index: digit === "Index",
            joint,
            digit: ["Thumb", "Index", "Middle", "Ring", "Little"].indexOf(
              digit,
            ),
          });
      }
  }
  private turn(node: THREE.Object3D, to: THREE.Vector3, hinge?: THREE.Vector3) {
    const rest = this.aims.get(node)!;
    this.vrm.scene.getWorldQuaternion(this.sceneRotation);
    this.sceneInverse.copy(this.sceneRotation).invert();
    to.applyQuaternion(this.sceneInverse).normalize();
    // Aim from the bind frame every time. Incremental rotations accumulate
    // roll when poses cycle and can eventually turn the palm inside out.
    this.delta.setFromUnitVectors(rest.direction, to);
    this.world
      .copy(rest.rotation)
      .premultiply(this.delta)
      .premultiply(this.sceneRotation);
    if (hinge && hinge.lengthSq() > 1e-8) {
      // A direction alone leaves axial roll unconstrained. Align the upper
      // arm's hinge frame to the actual shoulder/elbow/wrist plane, so its
      // inner elbow cannot turn backwards while the hand still reaches.
      this.hingeAxis
        .copy(rest.direction)
        .applyQuaternion(this.delta)
        .applyQuaternion(this.sceneRotation)
        .normalize();
      this.hingeCurrent.set(0, 0, 1).applyQuaternion(this.world);
      this.hingeCurrent
        .addScaledVector(this.hingeAxis, -this.hingeCurrent.dot(this.hingeAxis))
        .normalize();
      this.hingeDesired
        .copy(hinge)
        .addScaledVector(this.hingeAxis, -hinge.dot(this.hingeAxis))
        .normalize();
      const roll = Math.atan2(
        this.hingeAxis.dot(
          this.hingeCross.crossVectors(this.hingeCurrent, this.hingeDesired),
        ),
        this.hingeCurrent.dot(this.hingeDesired),
      );
      this.world.premultiply(
        // A strict hinge sign can demand almost a half turn at the shoulder.
        // Keep its axial correction bounded; the forearm still reaches the
        // same wrist goal, without folding the deltoid skin inside out.
        this.hingeRoll.setFromAxisAngle(
          this.hingeAxis,
          THREE.MathUtils.clamp(roll, -0.8, 0.8),
        ),
      );
    }
    if (node.parent) node.parent.getWorldQuaternion(this.parent).invert();
    else this.parent.identity();
    node.quaternion.copy(this.parent.multiply(this.world));
    node.updateWorldMatrix(false, true);
  }
  reset(smooth: number) {
    for (const finger of this.fingers)
      finger.node.quaternion.slerp(finger.rest, smooth);
  }
  update(
    goal: V3,
    wrist: V3,
    shape: HandShape,
    smooth: number,
    flutter: number,
    elbow?: V3,
    palm?: V3,
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
      (elbow?.[0] ?? sign * 0.36) * this.height,
      this.bottom + (elbow?.[1] ?? 0.62) * this.height,
      (elbow?.[2] ?? 0.18) * this.height,
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
    this.hingeNormal
      .crossVectors(
        this.hingeAxis.copy(this.elbow).sub(this.a),
        this.to.copy(this.target).sub(this.elbow),
      )
      .normalize()
      .multiplyScalar(-sign);
    this.turn(
      this.upper,
      this.to.copy(this.elbow).sub(this.a),
      this.hingeNormal,
    );
    this.upper.quaternion.slerp(this.oldUpper, 1 - smooth);
    this.upper.updateWorldMatrix(false, true);
    this.lower.getWorldPosition(this.b);
    this.hand.getWorldPosition(this.c);
    this.turn(this.lower, this.to.copy(this.target).sub(this.b));
    this.lower.getWorldQuaternion(this.world);
    if (!palm && shape === "thumbsup") {
      this.hand.getWorldPosition(this.c);
      this.lower.getWorldPosition(this.b);
      this.axis.copy(this.c).sub(this.b).normalize().multiplyScalar(sign);
      scene.getWorldQuaternion(this.sceneRotation);
      this.thumbUp.set(0, 1, 0).applyQuaternion(this.sceneRotation);
      this.thumbUp.addScaledVector(this.axis, -this.thumbUp.dot(this.axis));
      if (this.thumbUp.lengthSq() < 0.001) {
        this.thumbUp.set(0, 0, 1).applyQuaternion(this.sceneRotation);
        this.thumbUp.addScaledVector(this.axis, -this.thumbUp.dot(this.axis));
      }
      this.thumbUp.normalize();
      this.palmUp.crossVectors(this.thumbUp, this.axis).normalize();
      this.palm.setFromRotationMatrix(
        this.basis.makeBasis(this.axis, this.palmUp, this.thumbUp),
      );
    } else if (palm) {
      this.palm.setFromEuler(this.palmEuler.set(...palm));
      scene.getWorldQuaternion(this.sceneRotation);
      this.palm.premultiply(this.sceneRotation);
    } else {
      this.palm.setFromEuler(this.palmEuler.set(...wrist));
      this.palm.premultiply(this.handRest).premultiply(this.world);
    }
    this.palm.premultiply(this.parent.copy(this.world).invert()).normalize();
    if (this.palm.w < 0)
      this.palm.set(-this.palm.x, -this.palm.y, -this.palm.z, -this.palm.w);
    this.twist.set(this.palm.x, 0, 0, this.palm.w).normalize();
    const roll = THREE.MathUtils.clamp(
      2 * Math.atan2(this.twist.x, this.twist.w),
      -1.45,
      1.45,
    );
    this.twist.set(Math.sin(roll / 2), 0, 0, Math.cos(roll / 2));
    this.swing.copy(this.twist).invert().multiply(this.palm).normalize();
    const bend = 2 * Math.acos(THREE.MathUtils.clamp(this.swing.w, -1, 1));
    if (bend > 0.85) {
      this.palm.copy(this.swing);
      this.swing.identity().slerp(this.palm, 0.85 / bend);
    }
    // Pronation belongs to the forearm, while wrist flexion remains bounded.
    this.lower.quaternion.multiply(this.twist).slerp(this.oldLower, 1 - smooth);
    this.lower.updateWorldMatrix(false, true);
    this.hand.quaternion.slerp(this.swing, smooth);
    for (const finger of this.fingers) {
      let curl =
        shape === "soft"
          ? 0.28
          : shape === "clasp"
            ? 0.6
            : shape === "open"
              ? 0.025
              : 1;
      if (
        (shape === "point" && finger.index) ||
        (shape === "thumbsup" && finger.thumb)
      )
        curl = 0.015;
      const amount = [1.05, 1.25, 0.9][finger.joint];
      let y = 0,
        z = -sign * curl * amount;
      if (finger.thumb) {
        const closed = shape === "fist" || shape === "point";
        y =
          sign *
          (closed
            ? [1.15, 0, 0][finger.joint]
            : shape === "thumbsup"
              ? [-0.22, 0, 0][finger.joint]
              : 0.08);
        z =
          -sign *
          (closed
            ? [0.15, 0.35, 0.5][finger.joint]
            : shape === "soft"
              ? 0.12
              : 0.02);
      } else {
        z *= [0.95, 0.95, 1, 1.04, 1.08][finger.digit];
      }
      this.fingerTarget
        .setFromEuler(this.fingerEuler.set(0, y, z))
        .premultiply(finger.rest);
      finger.node.quaternion.slerp(this.fingerTarget, smooth);
    }
  }
}
