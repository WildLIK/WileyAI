import { useEffect, useState } from "react";
import { AvatarTests, neutralDemo } from "./AvatarTests";
import type { AvatarCapabilities } from "./avatarBehavior";
import { useAvatarDemo } from "./useAvatarDemo";

/** Controls only: reuse the existing avatar renderers without a third WebGL scene. */
export function AvatarTestWindow() {
  const { demo, setDemo } = useAvatarDemo();
  const [available, setAvailable] = useState<AvatarCapabilities | null>(null);
  const [error, setError] = useState("");
  const [initial] = useState(neutralDemo);
  useEffect(() => {
    let live = true;
    const accept = (value: AvatarCapabilities | null) => {
      if (live) setAvailable(value);
    };
    const off = window.wiley.onAvatarCapabilities(accept);
    void window.wiley
      .avatarCapabilities()
      .then(accept)
      .catch(() => {});
    void window.wiley
      .avatarDemo()
      .then((state) => {
        if (live) setDemo(state.demo || initial);
      })
      .catch((reason: Error) => {
        if (live) setError(reason.message);
      });
    return () => {
      live = false;
      off();
    };
  }, []);
  return (
    <main className="avatar-test-window">
      <p className="help">
        Панель рядом с феей. Масштаб модели и размер её окна меняются отдельно.
      </p>
      {error && <p role="alert">{error}</p>}
      {!available && (
        <p role="status">
          Ожидаю загрузку VRM. Если модель не выбрана, загрузите её в настройках
          аватара.
        </p>
      )}
      <AvatarTests
        value={demo || initial}
        expressions={available?.expressions || []}
        wings={available?.wings || 0}
        gestures={available?.gestures || false}
        onChange={setDemo}
        onClose={() =>
          void window.wiley
            .closeAvatarTest()
            .catch((reason: Error) => setError(reason.message))
        }
      />
      <p className="help">
        «Авто» или закрытие панели возвращают реакции по разговору. При проверке
        масштаб не меняется.
      </p>
    </main>
  );
}
