import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import { addAvatarLighting, fitAvatarCamera } from "./avatarPresentation";

export function Avatar({
  path,
  speaking = false,
}: {
  path: string;
  speaking?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const talking = useRef(speaking);
  const [error, setError] = useState("");
  useEffect(() => {
    talking.current = speaking;
  }, [speaking]);
  useEffect(() => {
    if (!path || !host.current) return;
    let disposed = false;
    let frame = 0;
    let vrm: VRM | undefined;
    let renderer: THREE.WebGLRenderer;
    let bounds: THREE.Box3 | undefined;
    const container = host.current;
    setError("");
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    } catch {
      setError("Не удалось включить 3D. Проверьте драйвер видеокарты.");
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NeutralToneMapping;
    container.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
    camera.position.set(0, 1.15, 3.1);
    camera.lookAt(0, 0.95, 0);
    addAvatarLighting(scene);
    const resize = () => {
      const width = container.clientWidth || 300;
      const height = container.clientHeight || 400;
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      if (bounds) fitAvatarCamera(camera, bounds);
    };
    let contextLost = false;
    const lost = (event: Event) => {
      event.preventDefault();
      contextLost = true;
      if (!disposed) setError("Восстанавливаю 3D после сбоя видеодрайвера…");
    };
    const restored = () => {
      contextLost = false;
      if (!disposed) {
        resize();
        setError("");
      }
    };
    renderer.domElement.addEventListener("webglcontextlost", lost);
    renderer.domElement.addEventListener("webglcontextrestored", restored);
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();
    const manager = new THREE.LoadingManager();
    manager.setURLModifier((url) => {
      if (url.startsWith("blob:") || url.startsWith("data:")) return url;
      throw new Error(
        "Аватар должен содержать встроенные текстуры, без внешних ссылок",
      );
    });
    const loader = new GLTFLoader(manager);
    loader.register((parser) => new VRMLoaderPlugin(parser));
    window.wiley
      .avatarBytes()
      .then(async (data) => {
        if (disposed) return;
        if (!data)
          throw new Error(
            "Не удалось прочитать файл аватара. Выберите VRM повторно в настройках.",
          );
        const gltf = await loader.parseAsync(new Uint8Array(data).buffer, "");
        if (disposed) {
          VRMUtils.deepDispose(gltf.scene);
          return;
        }
        const loaded = gltf.userData.vrm as VRM | undefined;
        if (!loaded) {
          VRMUtils.deepDispose(gltf.scene);
          throw new Error("В файле не найдена совместимая модель VRM");
        }
        vrm = loaded;
        VRMUtils.rotateVRM0(vrm);
        const leftArm = vrm.humanoid.getNormalizedBoneNode("leftUpperArm");
        const rightArm = vrm.humanoid.getNormalizedBoneNode("rightUpperArm");
        if (leftArm) leftArm.rotation.z = -1.1;
        if (rightArm) rightArm.rotation.z = 1.1;
        scene.add(vrm.scene);
        vrm.update(0);
        vrm.scene.updateMatrixWorld(true);
        bounds = new THREE.Box3().setFromObject(vrm.scene, true);
        fitAvatarCamera(camera, bounds);
      })
      .catch((error) => {
        if (!disposed) setError(error.message || "Не удалось загрузить VRM");
      });
    let previous = 0;
    const animate = (milliseconds: number) => {
      frame = requestAnimationFrame(animate);
      if (document.hidden || contextLost || milliseconds - previous < 1000 / 30)
        return;
      const delta = Math.min((milliseconds - previous) / 1000, 0.1);
      previous = milliseconds;
      const time = milliseconds / 1000;
      if (vrm) {
        vrm.expressionManager?.setValue(
          "blink",
          Math.sin(time * 1.1) > 0.992 ? 1 : 0,
        );
        vrm.expressionManager?.setValue(
          "aa",
          talking.current ? 0.15 + Math.abs(Math.sin(time * 10)) * 0.45 : 0,
        );
        const neck = vrm.humanoid.getNormalizedBoneNode("neck");
        if (neck) neck.rotation.z = Math.sin(time * 0.7) * 0.025;
        vrm.update(delta);
      }
      renderer.render(scene, camera);
    };
    frame = requestAnimationFrame(animate);
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      renderer.domElement.removeEventListener("webglcontextrestored", restored);
      if (vrm) VRMUtils.deepDispose(vrm.scene);
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [path]);
  return (
    <div className="avatar-stage" ref={host}>
      {!path && (
        <div className="avatar-placeholder">
          <div className={"orb " + (speaking ? "speaking" : "")}>
            <span>W</span>
          </div>
          <span>
            Загрузите свой VRM-аватар
            <br />в настройках персонажа
          </span>
        </div>
      )}
      {error && <div className="avatar-error">{error}</div>}
    </div>
  );
}
