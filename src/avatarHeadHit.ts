import * as THREE from "three";

/** A head-local ellipsoid avoids CPU skinning/raycasting the entire avatar. */
export class AvatarHeadHit {
  private readonly transform = new THREE.Matrix4();
  private readonly inverse = new THREE.Matrix4();
  private readonly position = new THREE.Vector3();
  private readonly rotation = new THREE.Quaternion();
  private readonly scale = new THREE.Vector3(1, 1, 1);
  private readonly localRay = new THREE.Ray();
  private readonly sphere = new THREE.Sphere(new THREE.Vector3(), 1);
  private readonly intersection = new THREE.Vector3();
  private readonly shape: THREE.Matrix4;
  private readonly head: THREE.Object3D;

  constructor(head: THREE.Object3D, height: number) {
    this.head = head;
    this.shape = new THREE.Matrix4()
      .makeTranslation(0, height * 0.085, 0)
      .scale(new THREE.Vector3(height * 0.075, height * 0.095, height * 0.075));
  }

  contains(ray: THREE.Ray) {
    this.head.getWorldPosition(this.position);
    this.head.getWorldQuaternion(this.rotation);
    this.transform.compose(this.position, this.rotation, this.scale);
    this.inverse.copy(this.transform.multiply(this.shape)).invert();
    this.localRay.copy(ray).applyMatrix4(this.inverse);
    return (
      this.localRay.intersectSphere(this.sphere, this.intersection) !== null
    );
  }
}
