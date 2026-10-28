import * as THREE from "three";
import { avatarZoom } from "./avatarBehavior.ts";

/** Neutral studio illumination avoids a blue/grey cast on pale anime avatars. */
export function addAvatarLighting(scene: THREE.Scene) {
  scene.add(new THREE.AmbientLight(0xffffff, 0.65));
  scene.add(new THREE.HemisphereLight(0xffffff, 0xc9c4cf, 0.3));
  const key = new THREE.DirectionalLight(0xfff5ee, 1.5);
  key.position.set(1, 2, 3);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xe8f3ff, 0.3);
  fill.position.set(-2, 1, 1);
  scene.add(fill);
}

// Scratch values: close-ups refit the camera every frame.
const size = new THREE.Vector3();
const focus = new THREE.Vector3();
const face = new THREE.Vector3();
const projections = new WeakMap<THREE.PerspectiveCamera, number[]>();

/** Fit both wingspan and height, including depth, for any companion panel size. */
export function fitAvatarCamera(
  camera: THREE.PerspectiveCamera,
  bounds: THREE.Box3,
  zoom = 1,
  head?: THREE.Vector3,
) {
  if (bounds.isEmpty()) return;
  bounds.getSize(size);
  const center = bounds.getCenter(focus);
  const tanHalfFov = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  const distance =
    Math.max(
      size.y / (2 * tanHalfFov),
      size.x / (2 * tanHalfFov * Math.max(camera.aspect, 0.01)),
      0.1,
    ) *
      1.1 +
    size.z / 2;
  camera.zoom = avatarZoom(zoom);
  if (head) face.copy(head).y += size.y * 0.04;
  else face.copy(center).y += size.y * 0.36;
  center.lerp(face, Math.min(1, Math.max(0, (camera.zoom - 1) / 2.5)));
  camera.position.copy(center);
  camera.position.z += distance;
  camera.near = Math.max(0.001, distance / 1000);
  camera.far = Math.max(20, distance + size.length() * 3);
  camera.lookAt(center);
  const applied = projections.get(camera);
  if (
    !applied ||
    applied[0] !== camera.aspect ||
    applied[1] !== camera.zoom ||
    applied[2] !== camera.near ||
    applied[3] !== camera.far ||
    applied[4] !== camera.fov
  ) {
    camera.updateProjectionMatrix();
    projections.set(camera, [
      camera.aspect,
      camera.zoom,
      camera.near,
      camera.far,
      camera.fov,
    ]);
  }
  camera.updateMatrixWorld();
}
