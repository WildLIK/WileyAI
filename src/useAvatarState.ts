import { useEffect, useRef, useState } from "react";
import { idleAvatar, type AvatarSignal } from "./avatarBehavior";

/** The desktop arbitrates presentation; a newly opened avatar receives the current turn. */
export function useAvatarState(local: AvatarSignal): AvatarSignal {
  const [shared, setShared] = useState<AvatarSignal>(idleAvatar);
  const revision = useRef(-1);
  useEffect(() => {
    if (!window.wiley.onAvatarState) return;
    let active = true;
    const accept = (value: AvatarSignal & { revision: number }) => {
      if (active && value.revision >= revision.current) {
        revision.current = value.revision;
        setShared(value);
      }
    };
    const off = window.wiley.onAvatarState(accept);
    void window.wiley
      .avatarState()
      .then(accept)
      .catch(() => {});
    return () => {
      active = false;
      off();
    };
  }, []);
  useEffect(() => {
    if (!window.wiley.updateAvatar) return;
    const publish = () => {
      void window.wiley.updateAvatar(local).catch(() => {});
    };
    publish();
    const timer = setInterval(publish, 4000);
    return () => clearInterval(timer);
  }, [
    local.phase,
    local.emotion,
    local.gesture,
    local.cue,
    local.voice,
    local.energy,
  ]);
  return typeof window.wiley.onAvatarState === "function" ? shared : local;
}
