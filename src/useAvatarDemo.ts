import { useEffect, useRef, useState } from "react";
import type { AvatarDemo, AvatarDemoState } from "./avatarBehavior";

/** A presentation-only preview shared by the existing renderers, with an owner lease. */
export function useAvatarDemo() {
  const [state, setState] = useState<AvatarDemoState>({
    demo: null,
    owner: false,
    revision: -1,
  });
  const latest = useRef(state);
  const accept = (value: AvatarDemoState) => {
    if (value.revision < latest.current.revision) return;
    latest.current = value;
    setState(value);
  };
  useEffect(() => {
    let live = true;
    const update = (value: AvatarDemoState) => {
      if (live) accept(value);
    };
    const off = window.wiley.onAvatarDemo(update);
    void window.wiley
      .avatarDemo()
      .then(update)
      .catch(() => {});
    return () => {
      live = false;
      off();
      if (latest.current.owner)
        void window.wiley.releaseAvatarDemo().catch(() => {});
    };
  }, []);
  useEffect(() => {
    if (!state.owner || !state.demo) return;
    const timer = setInterval(() => {
      if (latest.current.owner && latest.current.demo)
        void window.wiley
          .updateAvatarDemo(latest.current.demo, true)
          .catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, [state.owner, Boolean(state.demo)]);
  return {
    ...state,
    setDemo: (demo: AvatarDemo | null) => {
      void window.wiley
        .updateAvatarDemo(demo)
        .then(accept)
        .catch(() => {});
    },
  };
}
