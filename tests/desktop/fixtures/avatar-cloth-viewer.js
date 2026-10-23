import * as T from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import { AvatarMotion } from "/src/avatarMotion.ts";
import { addAvatarLighting } from "/src/avatarPresentation.ts";
const renderer = new T.WebGLRenderer({
  antialias: true,
  preserveDrawingBuffer: true,
});
renderer.setSize(700, 1000);
renderer.outputColorSpace = T.SRGBColorSpace;
renderer.toneMapping = T.NeutralToneMapping;
document.body.append(renderer.domElement);
const scene = new T.Scene();
scene.background = new T.Color(0x1c1e28);
addAvatarLighting(scene);
const camera = new T.PerspectiveCamera(32, 0.7, 0.01, 20);
const loader = new GLTFLoader();
loader.register((p) => new VRMLoaderPlugin(p));
const gltf = await loader.loadAsync("/model");
const vrm = gltf.userData.vrm;
VRMUtils.rotateVRM0(vrm);
scene.add(vrm.scene);
vrm.update(0);
vrm.scene.updateMatrixWorld(true);
const bounds = new T.Box3().setFromObject(vrm.scene);
const height = bounds.getSize(new T.Vector3()).y;
const motion = new AvatarMotion(vrm, height);
let time = 0;
const cloth = [];
vrm.scene.traverse((o) => {
  if (!o.isSkinnedMesh) return;
  let node = o;
  while (node) {
    if (node.name.includes("Responsive_Skirt")) {
      cloth.push(o);
      break;
    }
    node = node.parent;
  }
});
if (!cloth.length) throw Error("Responsive skirt meshes were not found");
const bone = (n) => vrm.humanoid.getNormalizedBoneNode(n);
const point = (n) => bone(n).getWorldPosition(new T.Vector3());
function collision(step = 1) {
  let inside = 0,
    min = 1,
    samples = 0;
  const legs = ["left", "right"].map((s) => [
    point(s + "UpperLeg"),
    point(s + "LowerLeg"),
  ]);
  const p = new T.Vector3();
  for (const mesh of cloth) {
    const count = mesh.geometry.attributes.position.count;
    for (let i = 0; i < count; i += step) {
      mesh.getVertexPosition(i, p);
      mesh.localToWorld(p);
      for (const [a, b] of legs) {
        const axis = b.clone().sub(a);
        const t = p.clone().sub(a).dot(axis) / axis.lengthSq();
        if (t < 0.09 || t > 0.93) continue;
        const closest = a.clone().addScaledVector(axis, t);
        const radius = 0.061 - 0.013 * t;
        const clearance = p.distanceTo(closest) - radius;
        samples++;
        min = Math.min(min, clearance);
        if (clearance < -0.001) inside++;
      }
    }
  }
  return { inside, minClearance: min, samples };
}
window.pose = (name, angle = 0, detail = false, motionEnabled = true) => {
  for (let i = 0; i < 180; i++) {
    time += 1 / 60;
    motion.update(
      time,
      1 / 60,
      {
        phase: "idle",
        emotion: "neutral",
        gesture: name,
        cue: name,
        voice: false,
        energy: 0,
      },
      {
        motion: motionEnabled,
        gaze: false,
        expressions: true,
        strength: 1,
        demo: true,
        still: true,
        pointer: { x: 0, y: 0 },
        yaw: angle,
      },
    );
  }
  vrm.scene.updateMatrixWorld(true);
  const torsoDetail = detail === "torso";
  const skirtDetail = detail === "skirt" || detail === "underneath";
  const target = skirtDetail
    ? point("hips").add(new T.Vector3(0, -0.035, 0))
    : torsoDetail
      ? point("neck").add(new T.Vector3(0, -0.14, 0))
      : detail
        ? point("head").add(new T.Vector3(0, 0.09, 0))
        : new T.Vector3(0, 0.91, 0);
  camera.position
    .copy(target)
    .add(
      new T.Vector3(
        0,
        detail === "underneath" ? -0.62 : detail ? 0.025 : 0.04,
        skirtDetail ? 0.92 : torsoDetail ? 1.05 : detail ? 0.82 : 3.5,
      ),
    );
  camera.lookAt(target);
  camera.updateProjectionMatrix();
  renderer.render(scene, camera);
  const active = {
    left: vrm.expressionManager.getValue("skirtRaiseLeft"),
    right: vrm.expressionManager.getValue("skirtRaiseRight"),
  };
  const withCloth = collision();
  vrm.expressionManager.setValue("skirtRaiseLeft", 0);
  vrm.expressionManager.setValue("skirtRaiseRight", 0);
  vrm.update(0);
  vrm.scene.updateMatrixWorld(true);
  const withoutCloth = collision();
  vrm.expressionManager.setValue("skirtRaiseLeft", active.left);
  vrm.expressionManager.setValue("skirtRaiseRight", active.right);
  vrm.update(0);
  vrm.scene.updateMatrixWorld(true);
  renderer.render(scene, camera);
  const armJoints = {};
  for (const side of ["left", "right"]) {
    armJoints[side] = ["UpperArm", "LowerArm", "Hand"].map((part) =>
      vrm.scene.worldToLocal(point(side + part)).toArray(),
    );
  }
  const armTwists = {};
  for (const side of ["left", "right"]) {
    const q = bone(side + "UpperArm").quaternion;
    armTwists[side] = 2 * Math.atan2(q.x, q.w);
  }
  return { name, active, withCloth, withoutCloth, armJoints, armTwists };
};
window.ready = true;
window.sweep = () => {
  const failures = [];
  let checks = 0,
    maxInside = 0,
    min = 1;
  for (const name of [
    "wave",
    "joy",
    "surprise",
    "explain",
    "think",
    "praise",
    "point",
    "listen",
    "thumbsup",
    "shy",
    "tired",
    "comfort",
    "dance",
    "dance2",
    "dance3",
  ]) {
    for (let i = 0; i < 180; i++) {
      time += 1 / 60;
      motion.update(
        time,
        1 / 60,
        {
          phase: "idle",
          emotion: "neutral",
          gesture: name,
          cue: name,
          voice: false,
          energy: 0,
        },
        {
          motion: true,
          gaze: false,
          expressions: true,
          strength: 1,
          demo: true,
          still: true,
          pointer: { x: 0, y: 0 },
          yaw: 0,
        },
      );
      if (i % 15) continue;
      vrm.scene.updateMatrixWorld(true);
      const c = collision(3);
      checks++;
      maxInside = Math.max(maxInside, c.inside);
      min = Math.min(min, c.minClearance);
      if (c.inside) failures.push({ name, frame: i, ...c });
    }
  }
  return { checks, maxInside, minClearance: min, failures };
};
