import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "./api";

type AudioState = {
  available: boolean;
  enabled: boolean;
  volume?: number;
  muted?: boolean;
  error?: string;
};
type Action =
  | "play"
  | "pause"
  | "media_status"
  | "set_volume"
  | "change_volume"
  | "mute"
  | "unmute"
  | "play_pause"
  | "next"
  | "previous"
  | "stop";

export function DeviceAudio() {
  const [state, setState] = useState<AudioState>();
  const [volume, setVolume] = useState(50);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const busy = useRef(false);
  const dirty = useRef(false);
  const alive = useRef(true);
  const generation = useRef(0);
  const load = useCallback(async () => {
    if (busy.current) return;
    const current = ++generation.current;
    try {
      const next = await request<AudioState>("/device/audio");
      if (!alive.current || current !== generation.current) return;
      setState(next);
      if (!dirty.current && next.volume !== undefined) setVolume(next.volume);
      setError("");
    } catch (reason) {
      if (alive.current && current === generation.current)
        setError(String(reason));
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void load();
    window.addEventListener("focus", load);
    const channel = new BroadcastChannel("wiley-ui");
    channel.onmessage = (event) => {
      if (event.data.type === "settings") void load();
    };
    return () => {
      alive.current = false;
      generation.current++;
      window.removeEventListener("focus", load);
      channel.close();
    };
  }, [load]);

  const execute = async (action: Action, value?: number) => {
    if (busy.current) return;
    busy.current = true;
    generation.current++; // Discard an older in-flight status read.
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const result = await request<{
        text: string;
        volume?: number;
        muted?: boolean;
      }>("/device/audio", "POST", {
        action,
        ...(value === undefined ? {} : { value }),
      });
      if (!alive.current) return;
      setNotice(result.text);
      if (result.volume !== undefined) {
        dirty.current = false;
        setVolume(result.volume);
        setState((previous) => ({
          ...previous,
          available: true,
          enabled: previous?.enabled ?? true,
          volume: result.volume,
          muted: result.muted,
        }));
      }
    } catch (reason) {
      if (alive.current) setError(String(reason));
    } finally {
      busy.current = false;
      if (alive.current) {
        setWorking(false);
        void load();
      }
    }
  };
  const blocked = working || !state?.enabled;
  return (
    <div
      className="card device-audio"
      aria-label="Звук Windows"
      aria-busy={working}
    >
      <div className="button-row">
        <h2>Звук Windows</h2>
        <button
          className="ghost"
          disabled={working}
          onClick={() => void load()}
        >
          Обновить громкость
        </button>
      </div>
      <p className="help">
        Устройство воспроизведения Windows по умолчанию. Выбранный в настройках
        динамик Уайли на него не влияет.
      </p>
      {state?.available && (
        <p className="help">
          Сейчас: {state.volume}% ·{" "}
          {state.muted ? "звук выключен" : "звук включён"}
        </p>
      )}
      {state && !state.available && <p className="help">{state.error}</p>}
      {state && !state.enabled && (
        <p className="help">
          Включите управление звуком в доступе к инструментам выше.
        </p>
      )}
      <label>
        Громкость Windows: {volume}%
        <input
          aria-label="Громкость Windows"
          type="range"
          min={0}
          max={100}
          step={1}
          value={volume}
          disabled={blocked || !state?.available}
          onChange={(event) => {
            dirty.current = true;
            setVolume(Number(event.target.value));
          }}
        />
      </label>
      <div className="button-row">
        <button
          className="outline"
          disabled={blocked || !state?.available}
          onClick={() => void execute("set_volume", volume)}
        >
          Применить громкость
        </button>
        <button
          className="outline"
          disabled={blocked || !state?.available}
          onClick={() => void execute("change_volume", -10)}
        >
          Тише на 10%
        </button>
        <button
          className="outline"
          disabled={blocked || !state?.available}
          onClick={() => void execute("change_volume", 10)}
        >
          Громче на 10%
        </button>
        <button
          className="outline"
          disabled={blocked || !state?.available}
          onClick={() => void execute(state?.muted ? "unmute" : "mute")}
        >
          {state?.muted ? "Включить звук" : "Выключить звук"}
        </button>
      </div>
      <div className="button-row">
        {(
          [
            ["play", "Продолжить музыку"],
            ["pause", "Поставить музыку на паузу"],
            ["media_status", "Проверить проигрыватель"],
            ["previous", "Предыдущий трек"],
            ["play_pause", "Воспроизведение / пауза"],
            ["next", "Следующий трек"],
            ["stop", "Остановить проигрыватель"],
          ] as const
        ).map(([action, label]) => (
          <button
            className="outline"
            key={action}
            disabled={blocked}
            onClick={() => void execute(action)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="help">
        «Громкость тридцать пять процентов» · «Сделай тише» · «Выключи звук» ·
        «Следующий трек». Для AIMP используется его API, для других плееров —
        медиасессия Windows. Пауза и продолжение проверяют прочитанное
        состояние. При отсутствии API для переключателя и треков доступны
        медиаклавиши Windows без подтверждения состояния.
      </p>
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
