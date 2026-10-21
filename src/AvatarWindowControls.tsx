import { useEffect, useState } from "react";

export function AvatarClose() {
  return (
    <button
      className="pet-close"
      aria-label="Закрыть окно аватара"
      title="Скрыть аватар; чат продолжит работать"
      onClick={() => void window.wiley.hideAvatar()}
    >
      ×
    </button>
  );
}

export function AvatarClickThrough() {
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true,
      frame = 0;
    const accept = (value: { clickThrough: boolean }) => {
      if (live) setEnabled(value.clickThrough);
    };
    const off = window.wiley.onAvatarControls(accept);
    void window.wiley
      .avatarControls()
      .then(accept)
      .catch(() => {});
    const host = document.querySelector(".pet-window")!;
    const selector =
      ".pet-drag, .pet-actions, .avatar-view-controls, .conversation-control, .pet-resize";
    const observed = new Set<Element>();
    const publish = () => {
      frame = 0;
      const nodes = [...host.querySelectorAll(selector)];
      for (const node of [
        ...nodes,
        ...host.querySelectorAll(".avatar-stage"),
      ]) {
        if (!observed.has(node)) {
          observed.add(node);
          resize.observe(node);
        }
      }
      const regions = nodes
        .map((node) => {
          const { x, y, width, height } = node.getBoundingClientRect();
          return { x, y, width, height };
        })
        .filter((rect) => rect.width > 0 && rect.height > 0);
      void window.wiley.setAvatarControlRegions(regions).catch(() => {});
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(publish);
    };
    const resize = new ResizeObserver(schedule);
    const mutations = new MutationObserver(schedule);
    resize.observe(host);
    mutations.observe(host, { childList: true, subtree: true });
    window.addEventListener("resize", schedule);
    schedule();
    return () => {
      live = false;
      off();
      resize.disconnect();
      mutations.disconnect();
      window.removeEventListener("resize", schedule);
      cancelAnimationFrame(frame);
    };
  }, []);
  return (
    <button
      aria-label="Пропуск кликов"
      aria-pressed={enabled}
      title={
        error ||
        "Кнопки остаются доступны. Переключить: Ctrl+Alt+A или пункт «Пропуск кликов» в трее."
      }
      onClick={() =>
        void window.wiley
          .clickThrough(!enabled)
          .then((value) => setEnabled(value.clickThrough))
          .catch((reason: Error) => setError(reason.message))
      }
    >
      {enabled ? "Клики проходят: вкл" : "Пропуск кликов"}
    </button>
  );
}
