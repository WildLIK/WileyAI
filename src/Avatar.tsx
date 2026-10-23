import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import type { Settings } from "./api";
import { addAvatarLighting, fitAvatarCamera } from "./avatarPresentation";
import { avatarZoom, type AvatarSignal } from "./avatarBehavior";
import { useAvatarDemo } from "./useAvatarDemo";
import { AvatarMotion } from "./avatarMotion";
import { AvatarMeter } from "./avatarMeter";
import { AvatarMusic } from "./avatarMusic";
import { avatarPointer } from "./avatarPointer";
import { avatarCaption } from "./avatarCaption";
import { AvatarHeadHit } from "./avatarHeadHit";

type Stats = {
  fps: number;
  cpu: number;
  gpu: number | null;
  triangles: number;
  device: string;
};
const cameraKey =
  "wiley-avatar-zoom-" +
  (new URLSearchParams(location.search).get("view") === "avatar"
    ? "desktop"
    : "panel");
function readZoom() {
  try {
    return avatarZoom(Number(localStorage.getItem(cameraKey) || 1));
  } catch {
    return 1;
  }
}

export function Avatar({
  path,
  signal,
  settings,
}: {
  path: string;
  signal: AvatarSignal;
  settings: Settings;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(readZoom);
  const [error, setError] = useState("");
  const [showStats, setShowStats] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const { demo, setDemo } = useAvatarDemo();
  const [caption, setCaption] = useState({
    name: "В покое",
    text: "Готова помочь",
  });
  const effectiveSignal = demo?.signal || signal;
  const config = useRef({ signal: effectiveSignal, settings, zoom, demo });
  config.current = { signal: effectiveSignal, settings, zoom, demo };
  const pointer = useRef({ x: 0, y: 0, yaw: 0 });
  const dragging = useRef<{ x: number; yaw: number } | null>(null);
  const refresh = useRef(() => {});
  function changeZoom(value: number) {
    const next = avatarZoom(value);
    setZoom(next);
    try {
      localStorage.setItem(cameraKey, String(next));
    } catch {
      /* The view still works without persistence. */
    }
  }
  function resetView() {
    pointer.current = { x: 0, y: 0, yaw: 0 };
    changeZoom(1);
    refresh.current();
  }
  useEffect(() => {
    refresh.current();
  }, [
    zoom,
    settings.avatar_fps,
    settings.avatar_motion,
    settings.avatar_gaze,
    settings.avatar_music,
    settings.avatar_expressions,
    Boolean(demo),
  ]);
  useEffect(() => {
    if (!path || !host.current) return;
    const container = host.current;
    let disposed = false,
      contextLost = false,
      nativeActive = true,
      receivedActivity = false,
      intersecting = true;
    let frame = 0,
      previous = 0,
      nextFrame = 0,
      elapsed = 0,
      frames = 0,
      sampleFrames = 0,
      cpu = 0,
      sampleStart = 0;
    let vrm: VRM | undefined,
      motion: AvatarMotion | undefined,
      bounds: THREE.Box3 | undefined,
      head: THREE.Vector3 | undefined;
    let renderer: THREE.WebGLRenderer;
    setError("");
    setStats(null);
    void window.wiley.reportAvatarCapabilities(null).catch(() => {});
    container.dataset.render = "loading";
    try {
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: "low-power",
      });
    } catch {
      setError("Не удалось включить 3D. Проверьте драйвер видеокарты.");
      container.dataset.render = "error";
      return;
    }
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NeutralToneMapping;
    const canvas = renderer.domElement;
    canvas.setAttribute(
      "aria-label",
      "3D-персонаж. Колесо — масштаб, перетаскивание — поворот",
    );
    container.prepend(canvas);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
    addAvatarLighting(scene);
    let meter = new AvatarMeter(renderer.getContext());
    const music = new AvatarMusic();
    let musicStatus = "";
    let captionKey = "";
    const facePoint = new THREE.Vector3();
    const petHead = new THREE.Vector3();
    let headHit: AvatarHeadHit | undefined;
    const ray = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let petUntil = 0;
    let petContext = false;
    const hitHead = (event: MouseEvent) => {
      if (!headHit) return false;
      const box = canvas.getBoundingClientRect();
      if (!box.width || !box.height) return false;
      mouse.set(
        ((event.clientX - box.x) / box.width) * 2 - 1,
        1 - ((event.clientY - box.y) / box.height) * 2,
      );
      ray.setFromCamera(mouse, camera);
      return headHit.contains(ray.ray);
    };
    const pet = (event: MouseEvent) => {
      if (event.button !== 2) return;
      const onHead = hitHead(event);
      const handled = onHead || (event.type === "contextmenu" && petContext);
      if (event.type === "pointerdown") petContext = onHead;
      if (event.type === "contextmenu") petContext = false;
      if (!handled) return;
      event.preventDefault();
      event.stopPropagation();
      if (onHead) petUntil = performance.now() + 2600;
    };
    const stroke = (event: PointerEvent) => {
      if (event.buttons & 2 && hitHead(event))
        petUntil = performance.now() + 1800;
    };
    canvas.addEventListener("pointerdown", pet);
    canvas.addEventListener("pointermove", stroke);
    canvas.addEventListener("contextmenu", pet);
    let watchingPointer = false;
    const watchPointer = (enabled: boolean) => {
      if (enabled === watchingPointer) return;
      watchingPointer = enabled;
      void window.wiley.watchAvatarPointer(enabled).catch(() => {});
    };
    const offPointer = window.wiley.onAvatarPointer((point) => {
      if (!watchingPointer || disposed) return;
      const box = canvas.getBoundingClientRect();
      if (!box.width || !box.height) return;
      const headNode = vrm?.humanoid.getNormalizedBoneNode("head");
      if (headNode) headNode.getWorldPosition(facePoint).project(camera);
      else facePoint.set(0, 0.55, 0);
      const target = avatarPointer(
        point,
        {
          x: box.x + ((facePoint.x + 1) * box.width) / 2,
          y: box.y + ((1 - facePoint.y) * box.height) / 2,
        },
        box,
      );
      pointer.current.x = target.x;
      pointer.current.y = target.y;
    });
    const stop = () => {
      watchPointer(false);
      music.setEnabled(false);
      cancelAnimationFrame(frame);
      frame = 0;
      previous = 0;
      nextFrame = 0;
      sampleStart = 0;
      sampleFrames = 0;
      cpu = 0;
      petUntil = 0;
    };
    const animate = (milliseconds: number) => {
      if (disposed || container.dataset.render !== "running") return;
      frame = requestAnimationFrame(animate);
      const { signal, settings, demo } = config.current;
      // UI/system animation preferences govern the interface. The avatar has
      // explicit motion, gaze, music and FPS controls of its own.
      const fps = settings.avatar_fps || 60;
      const interval = 1000 / fps;
      container.dataset.targetFps = String(fps);
      if (milliseconds < nextFrame - 0.5) return;
      // Keep the deadline between refreshes so 30 FPS also works on displays
      // whose refresh rate is not divisible by 30. Never catch up after a stall.
      nextFrame =
        nextFrame && milliseconds - nextFrame < interval
          ? nextFrame + interval
          : milliseconds + interval;
      const delta = previous
        ? Math.min((milliseconds - previous) / 1000, 0.1)
        : 1 / fps;
      previous = milliseconds;
      elapsed += delta;
      if (!sampleStart) sampleStart = milliseconds - delta * 1000;
      const began = performance.now();
      motion?.update(elapsed, delta, signal, {
        motion: demo ? !demo.still : settings.avatar_motion !== false,
        gaze: !demo && settings.avatar_gaze !== false,
        expressions: Boolean(demo) || settings.avatar_expressions !== false,
        strength: demo?.strength ?? settings.avatar_expression_strength ?? 0.65,
        still: demo?.still,
        demo: Boolean(demo),
        pointer: pointer.current,
        yaw: pointer.current.yaw,
        music: music.value,
        pet: Math.min(1, Math.max(0, (petUntil - milliseconds) / 650)),
      });
      const status = demo
        ? "Ручной тест · «Авто» включает реакции на музыку"
        : settings.avatar_motion === false
          ? "Музыка: движения выключены"
          : settings.avatar_music === false
            ? "Музыка: выключено в настройках"
            : music.value.error ||
              (music.value.active
                ? `Звук: ${music.value.source}${signal.phase !== "idle" ? " · пауза на время разговора" : music.value.bpm ? ` · ≈${music.value.bpm} уд/мин` : ""}`
                : music.value.players?.length
                  ? `Ожидаю звук · ${music.value.players.join(", ")}`
                  : "Ожидаю звук плеера или браузера");
      if (status !== musicStatus) {
        musicStatus = status;
        container.querySelector(".avatar-music-status")!.textContent = status;
        container
          .querySelector(".avatar-music-status")!
          .setAttribute("title", status);
      }
      const nextCaption =
        motion && motion.petWeight > 0.1
          ? { name: "Поглаживание", text: "Мне приятно, спасибо" }
          : avatarCaption(motion?.pose || "none", signal.emotion, signal.phase);
      const nextKey = nextCaption.name + nextCaption.text;
      if (captionKey !== nextKey) {
        captionKey = nextKey;
        setCaption(nextCaption);
      }
      container.style.setProperty("--music-level", String(music.value.level));
      container.dataset.dancing = String(
        Boolean(motion?.pose.startsWith("dance")),
      );
      container.dataset.musicSource = music.value.source;
      container.dataset.headYaw = (
        vrm?.humanoid.getNormalizedBoneNode("head")?.rotation.y || 0
      ).toFixed(3);
      container.dataset.eyeYaw = (vrm?.lookAt?.yaw || 0).toFixed(2);
      container.dataset.pose = motion?.pose || "none";
      container.dataset.petting = String((motion?.petWeight || 0) > 0.1);
      container.dataset.blush = (motion?.blush || 0).toFixed(3);
      container.dataset.skirtLeft = (
        vrm?.expressionManager?.getValue("skirtRaiseLeft") || 0
      ).toFixed(3);
      container.dataset.skirtRight = (
        vrm?.expressionManager?.getValue("skirtRaiseRight") || 0
      ).toFixed(3);
      container.dataset.smile = (
        vrm?.expressionManager?.getValue("happy") || 0
      ).toFixed(3);
      if (vrm && bounds) {
        const h = bounds.getSize(new THREE.Vector3()).y;
        vrm.humanoid.getNormalizedBoneNode("head")?.getWorldPosition(petHead);
        petHead.y += h * 0.067;
        facePoint.copy(petHead);
        facePoint.x += h * 0.072;
        facePoint.project(camera);
        petHead.project(camera);
        container.dataset.headX = (
          ((petHead.x + 1) * canvas.clientWidth) /
          2
        ).toFixed(1);
        container.dataset.headY = (
          ((1 - petHead.y) * canvas.clientHeight) /
          2
        ).toFixed(1);
        const x = ((petHead.x + 1) * canvas.clientWidth) / 2,
          y = ((1 - petHead.y) * canvas.clientHeight) / 2;
        const r = (Math.abs(facePoint.x - petHead.x) * canvas.clientWidth) / 2;
        const region = container.querySelector<HTMLElement>(
          ".avatar-head-region",
        )!;
        const left = Math.max(0, x - r),
          top = Math.max(0, y - r * 1.1);
        Object.assign(region.style, {
          left: left + "px",
          top: top + "px",
          width: Math.max(0, Math.min(canvas.clientWidth, x + r) - left) + "px",
          height:
            Math.max(0, Math.min(canvas.clientHeight, y + r * 1.1) - top) +
            "px",
        });
      }
      container.dataset.gazeX = pointer.current.x.toFixed(2);
      container.dataset.gazeY = pointer.current.y.toFixed(2);
      container.dataset.energy = (signal.energy || 0).toFixed(2);
      if (vrm && bounds && config.current.zoom > 1.5) {
        vrm.humanoid.getNormalizedBoneNode("head")?.getWorldPosition(head!);
        fitAvatarCamera(camera, bounds, config.current.zoom, head);
      }
      meter.begin(milliseconds);
      renderer.render(scene, camera);
      meter.end();
      cpu += performance.now() - began;
      sampleFrames++;
      frames++;
      container.dataset.renderFrames = String(frames);
      container.dataset.mouth =
        signal.phase === "speaking" ? "active" : "closed";
      if (milliseconds - sampleStart >= 1000) {
        setStats({
          fps: (sampleFrames * 1000) / (milliseconds - sampleStart),
          cpu: cpu / sampleFrames,
          gpu: meter.gpuMs,
          triangles: renderer.info.render.triangles,
          device: meter.device,
        });
        sampleStart = milliseconds;
        cpu = 0;
        sampleFrames = 0;
      }
    };
    const resize = () => {
      const width = container.clientWidth,
        height = Math.max(
          1,
          container.clientHeight -
            (parseFloat(
              getComputedStyle(container).getPropertyValue("--avatar-footer"),
            ) || 86),
        );
      if (!width || !height || contextLost) return;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
      renderer.setSize(width, height);
      camera.aspect = width / height;
      if (bounds) fitAvatarCamera(camera, bounds, config.current.zoom, head);
    };
    const resume = () => {
      stop();
      if (disposed) return;
      if (contextLost) {
        container.dataset.render = "lost";
        return;
      }
      if (!vrm) {
        container.dataset.render = "loading";
        return;
      }
      if (
        !nativeActive ||
        document.hidden ||
        !intersecting ||
        !container.clientWidth ||
        !container.clientHeight
      ) {
        container.dataset.render = "paused";
        return;
      }
      resize();
      container.dataset.render = "running";
      watchPointer(
        !config.current.demo && config.current.settings.avatar_gaze !== false,
      );
      music.setEnabled(
        !config.current.demo &&
          config.current.settings.avatar_motion !== false &&
          config.current.settings.avatar_music !== false,
      );
      frame = requestAnimationFrame(animate);
    };
    refresh.current = resume;
    const observer = new ResizeObserver(resume);
    observer.observe(container);
    const intersection = new IntersectionObserver(([entry]) => {
      intersecting = entry.isIntersecting;
      resume();
    });
    intersection.observe(container);
    const activity = (state: { visible: boolean }) => {
      nativeActive = state.visible;
      resume();
    };
    const offActivity = window.wiley.onWindowActivity((state) => {
      receivedActivity = true;
      activity(state);
    });
    void window.wiley
      .windowActivity()
      .then((state) => {
        if (!disposed && !receivedActivity) activity(state);
      })
      .catch(() => {});
    const lost = (event: Event) => {
      event.preventDefault();
      contextLost = true;
      stop();
      container.dataset.render = "lost";
      if (!disposed) setError("Восстанавливаю 3D после сбоя видеодрайвера…");
    };
    const restored = () => {
      contextLost = false;
      meter.dispose();
      meter = new AvatarMeter(renderer.getContext());
      if (!disposed) {
        setError("");
        resume();
      }
    };
    const wheel = (event: WheelEvent) => {
      if (event.target !== canvas) return;
      event.preventDefault();
      changeZoom(
        config.current.zoom *
          Math.exp(-Math.max(-200, Math.min(200, event.deltaY)) * 0.002),
      );
    };
    container.addEventListener("wheel", wheel, { passive: false });
    canvas.addEventListener("webglcontextlost", lost);
    canvas.addEventListener("webglcontextrestored", restored);
    document.addEventListener("visibilitychange", resume);
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
    void window.wiley
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
        VRMUtils.combineSkeletons(vrm.scene);
        VRMUtils.combineMorphs(vrm);
        scene.add(vrm.scene);
        vrm.scene.updateMatrixWorld(true);
        const height = new THREE.Box3()
          .setFromObject(vrm.scene, true)
          .getSize(new THREE.Vector3()).y;
        motion = new AvatarMotion(vrm, height);
        void window.wiley
          .reportAvatarCapabilities({
            expressions: [
              "happy",
              "sad",
              "angry",
              "surprised",
              "relaxed",
              "aa",
              "ou",
            ].filter(
              (name) =>
                (vrm!.expressionManager?.getExpression(name)?.binds.length ||
                  0) > 0,
            ),
            wings: motion.wingCount,
            gestures: Boolean(
              vrm.humanoid.getNormalizedBoneNode("rightUpperArm") &&
              vrm.humanoid.getNormalizedBoneNode("rightLowerArm"),
            ),
          })
          .catch(() => {});
        vrm.update(0);
        vrm.scene.updateMatrixWorld(true);
        bounds = new THREE.Box3().setFromObject(vrm.scene, true);
        head = vrm.humanoid
          .getNormalizedBoneNode("head")
          ?.getWorldPosition(new THREE.Vector3());
        const headNode = vrm.humanoid.getNormalizedBoneNode("head");
        if (headNode) headHit = new AvatarHeadHit(headNode, height);
        bounds.max.y += height * 0.1;
        container.dataset.ready = "true";
        resume();
      })
      .catch((error) => {
        if (!disposed) {
          container.dataset.render = "error";
          setError(error.message || "Не удалось загрузить VRM");
        }
      });
    return () => {
      disposed = true;
      void window.wiley.reportAvatarCapabilities(null).catch(() => {});
      stop();
      refresh.current = () => {};
      observer.disconnect();
      intersection.disconnect();
      offActivity();
      offPointer();
      container.removeEventListener("wheel", wheel);
      canvas.removeEventListener("pointerdown", pet);
      canvas.removeEventListener("pointermove", stroke);
      canvas.removeEventListener("contextmenu", pet);
      canvas.removeEventListener("webglcontextlost", lost);
      canvas.removeEventListener("webglcontextrestored", restored);
      document.removeEventListener("visibilitychange", resume);
      meter.dispose();
      if (vrm) VRMUtils.deepDispose(vrm.scene);
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    };
  }, [path]);
  return (
    <div
      className="avatar-stage"
      ref={host}
      data-phase={effectiveSignal.phase}
      data-emotion={
        !demo && settings.avatar_expressions === false
          ? "neutral"
          : effectiveSignal.emotion
      }
      data-testing={Boolean(demo)}
      data-demo={demo?.label || ""}
      data-zoom={zoom.toFixed(2)}
      onPointerDown={(event) => {
        if (!(event.target instanceof HTMLCanvasElement) || event.button !== 0)
          return;
        dragging.current = { x: event.clientX, yaw: pointer.current.yaw };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        if (dragging.current)
          pointer.current.yaw = THREE.MathUtils.clamp(
            dragging.current.yaw + (event.clientX - dragging.current.x) * 0.005,
            -0.6,
            0.6,
          );
      }}
      onPointerUp={(event) => {
        dragging.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId))
          event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onLostPointerCapture={() => {
        dragging.current = null;
      }}
      onDoubleClick={(event) => {
        if (event.target instanceof HTMLCanvasElement) resetView();
      }}
    >
      <div className="avatar-music-status" aria-label="Состояние музыки" />
      <div
        className="avatar-head-region"
        aria-hidden="true"
        style={{ position: "absolute", pointerEvents: "none" }}
      />
      <div className="avatar-caption" aria-label="Текущая анимация">
        <div>
          <small>{caption.name}</small>
          <span>{caption.text}</span>
        </div>
        {demo && (
          <button
            title="Завершить ручной тест и включить обычные реакции"
            onClick={() => setDemo(null)}
          >
            Авто
          </button>
        )}
      </div>
      {path && (
        <div
          className="avatar-view-controls"
          role="group"
          aria-label="Вид аватара"
        >
          <button
            aria-label="Отдалить аватара"
            title="Отдалить"
            disabled={zoom <= 0.7}
            onClick={() => changeZoom(zoom / 1.15)}
          >
            −
          </button>
          <button
            aria-label="Сбросить вид аватара"
            title="Полный рост · двойной щелчок по модели"
            onClick={resetView}
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            aria-label="Приблизить аватара"
            title="Приблизить"
            disabled={zoom >= 6}
            onClick={() => changeZoom(zoom * 1.15)}
          >
            +
          </button>
          <button
            aria-label="Крупный план лица"
            title="Приблизить лицо"
            onClick={() => changeZoom(4.8)}
          >
            Лицо
          </button>
          <button
            aria-label="Статистика 3D"
            aria-expanded={showStats}
            onClick={() => setShowStats(!showStats)}
          >
            FPS
          </button>
        </div>
      )}
      {showStats && (
        <output
          className="avatar-statistics"
          title={stats?.device || "Измеряю рендер"}
        >
          {stats ? (
            <>
              {stats.fps.toFixed(0)} FPS · предел {settings.avatar_fps || 60}
              <br />
              Кадр JS {stats.cpu.toFixed(1)} мс
              <br />
              GPU{" "}
              {stats.gpu === null
                ? "недоступно"
                : stats.gpu.toFixed(1) + " мс"}{" "}
              · {Math.round(stats.triangles / 1000)} тыс. треугольников
            </>
          ) : (
            "Измеряю рендер…"
          )}
        </output>
      )}
      {error && (
        <div className="avatar-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
