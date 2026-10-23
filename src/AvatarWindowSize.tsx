import { useEffect, useRef, useState } from "react";

export function AvatarWindowSize() {
  const [size, setSize] = useState({ width: innerWidth, height: innerHeight });
  const [error, setError] = useState("");
  const [resizing, setResizing] = useState(false);
  const dragging = useRef<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);
  const frame = useRef(0);
  const pending = useRef(size);
  useEffect(() => {
    let live = true;
    const accept = (value: typeof size) => {
      if (live) setSize(value);
    };
    const off = window.wiley.onAvatarSize(accept);
    void window.wiley
      .avatarSize()
      .then(accept)
      .catch(() => {});
    return () => {
      live = false;
      off();
      cancelAnimationFrame(frame.current);
    };
  }, []);
  function resize(value: Parameters<Window["wiley"]["resizeAvatar"]>[0]) {
    return window.wiley
      .resizeAvatar(value)
      .then(setSize)
      .catch((reason: Error) => setError(reason.message));
  }
  function finishResize() {
    if (!dragging.current) return;
    dragging.current = null;
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    void resize(pending.current).finally(() => setResizing(false));
  }
  return (
    <>
      <div
        className="pet-size-controls"
        role="group"
        aria-label="Размер окна феи"
      >
        <button
          aria-label="Уменьшить окно феи"
          title="Уменьшить окно"
          onClick={() => resize({ scale: 1 / 1.15 })}
        >
          −
        </button>
        <output title="Размер окна, ширина × высота">
          {size.width}×{size.height}
        </output>
        <button
          aria-label="Увеличить окно феи"
          title="Увеличить окно"
          onClick={() => resize({ scale: 1.15 })}
        >
          +
        </button>
      </div>
      <button
        className="pet-resize"
        data-resizing={resizing}
        aria-label="Изменить размер окна феи"
        title={
          error ||
          "Потяните за угол, чтобы изменить размер окна. Стрелки — шаг 32 пикселя."
        }
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          dragging.current = { x: event.screenX, y: event.screenY, ...size };
          pending.current = size;
          setResizing(true);
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const start = dragging.current;
          if (!start) return;
          pending.current = {
            width: start.width + event.screenX - start.x,
            height: start.height + event.screenY - start.y,
          };
          if (!frame.current)
            frame.current = requestAnimationFrame(() => {
              frame.current = 0;
              resize(pending.current);
            });
        }}
        onPointerUp={(event) => {
          finishResize();
          if (event.currentTarget.hasPointerCapture(event.pointerId))
            event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onLostPointerCapture={finishResize}
        onKeyDown={(event) => {
          const delta = {
            ArrowLeft: [-32, 0],
            ArrowRight: [32, 0],
            ArrowUp: [0, -32],
            ArrowDown: [0, 32],
          }[event.key];
          if (!delta) return;
          event.preventDefault();
          resize({ deltaWidth: delta[0], deltaHeight: delta[1] });
        }}
      >
        ◢
      </button>
    </>
  );
}
