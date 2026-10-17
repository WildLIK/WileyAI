import { useEffect, useState } from "react";
import { request } from "./api";

type State = {
  current_version: string;
  automatic: boolean;
  checked_at: number | null;
  available: { version: string; url: string } | null;
  dismissed: string;
  checking: boolean;
  has_key: boolean;
  error: string;
};

function useUpdates() {
  const [state, setState] = useState<State | null>(null);
  useEffect(() => {
    let active = true;
    const load = () =>
      request<State>("/updates")
        .then((value) => {
          if (active) setState(value);
        })
        .catch(() => {});
    void load();
    const timer = setInterval(load, 30000);
    const changed = () => {
      void load();
    };
    window.addEventListener("wiley-updates", changed);
    return () => {
      active = false;
      clearInterval(timer);
      window.removeEventListener("wiley-updates", changed);
    };
  }, []);
  return [
    state,
    (value: State, notify = true) => {
      setState(value);
      if (notify) window.dispatchEvent(new Event("wiley-updates"));
    },
  ] as const;
}

export function UpdateNotice() {
  const [state, setState] = useUpdates();
  if (!state?.available || state.dismissed === state.available.version)
    return null;
  return (
    <div className="update-notice">
      <span>Доступна WileyAI {state.available.version}</span>
      <button onClick={() => void window.wiley.openUpdate()}>
        Открыть выпуск
      </button>
      <button
        aria-label="Скрыть уведомление об обновлении"
        onClick={() =>
          void request<State>("/updates/dismiss", "POST").then(setState)
        }
      >
        ×
      </button>
    </div>
  );
}

export function UpdatesPanel() {
  const [state, setState] = useUpdates();
  const [token, setToken] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const action = async (route: string, method: string, body?: unknown) => {
    setWorking(true);
    setError("");
    try {
      setState(await request<State>(route, method, body));
      setToken("");
    } catch (error) {
      if (state) setState(state);
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  };
  return (
    <div className="card updates-panel">
      <h2>Обновления WileyAI</h2>
      <p className="help">
        Версия {state?.current_version ?? "…"}. Новые версии публикуются в
        GitHub Releases.
      </p>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={state?.automatic ?? true}
          disabled={working || !state}
          onChange={(event) => {
            const automatic = event.target.checked;
            if (state) setState({ ...state, automatic }, false);
            void action("/updates", "PUT", { automatic });
          }}
        />
        Проверять обновления автоматически
      </label>
      <div className="actions">
        <button
          className="outline"
          disabled={working || state?.checking}
          onClick={() => action("/updates/check", "POST")}
        >
          {working ? "Проверка…" : "Проверить обновления"}
        </button>
        <button
          className="outline"
          onClick={() => void window.wiley.openUpdate()}
        >
          Выпуски на GitHub
        </button>
      </div>
      {state?.available && (
        <p>
          Доступна версия {state.available.version}. Скачайте и запустите новый
          установщик.
        </p>
      )}
      {state?.checked_at && (
        <small>
          Последняя проверка:{" "}
          {new Date(state.checked_at * 1000).toLocaleString("ru-RU")}
          {!state.error && !state.available
            ? " · установлена актуальная версия"
            : ""}
        </small>
      )}
      {(error || state?.error) && (
        <p className="help" role="status">
          {error || state?.error}
        </p>
      )}
      <details className="cloud-details">
        <summary>
          Доступ к закрытому репозиторию
          {state?.has_key ? " · ключ сохранён" : ""}
        </summary>
        <p className="help">
          Для публичного проекта ключ не нужен. Для закрытого WileyAI
          используйте ключ GitHub с правом чтения Contents этого репозитория.
          Ключ хранится в Windows и не входит в резервные копии.
        </p>
        <label>
          Ключ GitHub
          <input
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder={state?.has_key ? "Сохранён в Windows" : "github_pat_…"}
          />
        </label>
        <div className="actions">
          <button
            className="outline"
            disabled={working || !token || !state}
            onClick={() =>
              action("/updates", "PUT", { automatic: state!.automatic, token })
            }
          >
            Сохранить ключ GitHub
          </button>
          {state?.has_key && (
            <button
              className="outline"
              disabled={working}
              onClick={() =>
                action("/updates", "PUT", {
                  automatic: state.automatic,
                  token: "",
                })
              }
            >
              Удалить ключ GitHub
            </button>
          )}
        </div>
      </details>
      <p className="help">
        Проверка через 15 секунд после запуска и затем раз в 6 часов. Windows
        уведомляет о каждой версии один раз. Установка обновления запускается
        вами.
      </p>
    </div>
  );
}
