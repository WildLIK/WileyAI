import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "./api";
import { ProcessStatus } from "./ProcessStatus";

type Player = {
  available: boolean;
  title: string;
  artists: string;
  playing: boolean;
  liked: boolean | null;
  volume: number | null;
};
type Connection = {
  connected: boolean;
  selected: boolean;
  state?: Player;
  restart_required?: boolean;
  text?: string;
  error?: string;
  enabled?: boolean;
};
const describeError = (reason: unknown) =>
  reason instanceof TypeError
    ? "Не удалось получить ответ локального ядра WileyAI. Проверьте, что программа работает, и повторите подключение."
    : String(reason).replace(/^Error: /, "");

export function YandexMusic({ onChanged }: { onChanged: () => Promise<void> }) {
  const [connection, setConnection] = useState<Connection>();
  const [query, setQuery] = useState("");
  const [volume, setVolume] = useState(50);
  const [working, setWorking] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const alive = useRef(true),
    busy = useRef(false),
    generation = useRef(0);
  const load = useCallback(async () => {
    if (busy.current) return;
    const current = ++generation.current;
    try {
      const result = await request<Connection>("/music/yandex");
      if (!alive.current || generation.current !== current) return;
      setConnection((previous) => ({
        ...result,
        restart_required: !result.connected && previous?.restart_required,
      }));
      if (result.state?.volume != null) setVolume(result.state.volume);
    } catch (reason) {
      if (alive.current && generation.current === current)
        setError(describeError(reason));
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void load();
    window.addEventListener("focus", load);
    return () => {
      alive.current = false;
      generation.current++;
      window.removeEventListener("focus", load);
    };
  }, [load]);
  const run = async (path: string, body: object, label: string) => {
    if (busy.current) return;
    busy.current = true;
    generation.current++;
    setWorking(label);
    setError("");
    setNotice("");
    try {
      const result = await request<Connection & { text: string }>(
        "/music/yandex/" + path,
        "POST",
        body,
      );
      if (!alive.current) return;
      setNotice(result.text);
      window.dispatchEvent(new Event("wiley-data-updated"));
      if (path !== "action") {
        setConnection(result);
      }
    } catch (reason) {
      if (alive.current) setError(describeError(reason));
    } finally {
      if (path !== "action") {
        try {
          await onChanged();
        } catch (reason) {
          if (alive.current)
            setError((previous) => previous || describeError(reason));
        }
      }
      busy.current = false;
      if (alive.current) {
        setWorking("");
        void load();
      }
    }
  };
  const action = (action: string, extra = {}) =>
    void run(
      "action",
      { action, ...extra },
      action === "search_play"
        ? "Ищу песню и проверяю воспроизведение…"
        : "Проверяю результат команды…",
    );
  const blocked =
    !!working || !connection?.connected || connection.enabled === false;
  return (
    <section
      className="card yandex-music"
      aria-label="Яндекс Музыка"
      aria-busy={!!working}
    >
      <div className="button-row">
        <h2>Яндекс Музыка</h2>
        <button
          className="ghost"
          disabled={!!working}
          onClick={() => void load()}
        >
          Проверить подключение
        </button>
      </div>
      <p className="help">
        Подключите настольную Яндекс Музыку или YandexMusicMod. Музыкальные
        команды в чате и голосом будут относиться к этому плееру. Если сборке
        нужны права администратора, Windows запросит подтверждение запуска.
      </p>
      <div className="button-row">
        <button
          className="outline"
          disabled={!!working || connection?.connected}
          onClick={() => void run("connect", {}, "Подключаю Яндекс Музыку…")}
        >
          Подключить Яндекс Музыку
        </button>
        {(connection?.connected || connection?.selected) && (
          <button
            className="outline"
            disabled={!!working}
            onClick={() => void run("disconnect", {}, "Отключаю управление…")}
          >
            Отключить управление
          </button>
        )}
      </div>
      {connection?.restart_required && (
        <div className="music-restart" role="status">
          <p>
            Для подключения нужно перезапустить открытый плеер. Текущее
            воспроизведение остановится.
          </p>
          <button
            className="outline"
            disabled={!!working}
            onClick={() =>
              void run(
                "connect",
                { restart: true },
                "Перезапускаю и подключаю плеер…",
              )
            }
          >
            Перезапустить и подключить
          </button>
        </div>
      )}
      {connection?.selected && !connection.connected && (
        <p className="help">
          Выбрана Яндекс Музыка, но связь недоступна. Подключите плеер повторно.
        </p>
      )}
      {connection?.error && !connection.connected && (
        <p className="help">{connection.error}</p>
      )}
      {connection?.state?.available && (
        <p role="status">
          {connection.state.playing ? "Воспроизведение" : "Пауза"} ·{" "}
          {connection.state.artists} — {connection.state.title}
          {connection.state.liked === true ? " · В любимых" : ""}
        </p>
      )}
      <div className="button-row">
        {(
          [
            ["previous", "Предыдущая песня"],
            ["play", "Плей"],
            ["pause", "Пауза"],
            ["next", "Следующая песня"],
            ["like", "Добавить в любимые"],
            ["unlike", "Убрать из любимых"],
          ] as const
        ).map(([key, label]) => (
          <button
            className="outline"
            key={key}
            disabled={blocked}
            onClick={() => action(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <label>
        Громкость Яндекс Музыки: {volume}%
        <input
          aria-label="Громкость Яндекс Музыки"
          type="range"
          min={0}
          max={100}
          value={volume}
          disabled={blocked}
          onChange={(event) => setVolume(Number(event.target.value))}
        />
      </label>
      <button
        className="outline"
        disabled={blocked}
        onClick={() => action("volume", { value: volume })}
      >
        Применить громкость плеера
      </button>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          action("search_play", { query });
        }}
      >
        <label>
          Исполнитель и название песни
          <input
            aria-label="Исполнитель и название песни"
            maxLength={200}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Linkin Park With You"
            disabled={blocked}
          />
        </label>
        <button
          className="outline"
          disabled={blocked || query.trim().length < 2}
        >
          Найти и включить
        </button>
      </form>
      <p className="help">
        «Найди песню линкин парк виз ю» · «Пауза» · «Следующая песня» · «Добавь
        в любимые» · «Громкость музыки 30 процентов». При нескольких близких
        результатах Уайли попросит уточнение.
      </p>
      {working && (
        <ProcessStatus
          kind={working.startsWith("Ищу") ? "search" : "brain"}
          label={working}
          detail={
            /подключ/i.test(working)
              ? "Если появился запрос Windows, подтвердите запуск плеера"
              : undefined
          }
        />
      )}
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
