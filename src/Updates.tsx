import { useCallback, useEffect, useState } from "react";
import { request } from "./api";

type State = {
  current_version: string;
  automatic: boolean;
  checked_at: number | null;
  available: { version: string; url: string; notes?: string; size?: number; date?: string } | null;
  signed: boolean;
  downloaded: boolean;
  progress: number | null;
  retention_days: 1 | 7 | 30;
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
  const publish = useCallback((value: State, notify = true) => {
      setState(value);
      if (notify) window.dispatchEvent(new Event("wiley-updates"));
    }, []);
  return [state, publish] as const;
}

export function UpdateNotice({ showUpdates }: { showUpdates: () => void }) {
  const [state, setState] = useUpdates();
  if (!state?.available || state.dismissed === state.available.version)
    return null;
  return (
    <div className="update-notice">
      <span>Доступна WileyAI {state.available.version}</span>
      <button onClick={() => state.signed ? showUpdates() : void window.wiley.openUpdate()}>
        {state.signed ? "Посмотреть обновление" : "Открыть выпуск"}
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
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const action = async (route: string, method: string, body?: unknown) => {
    setWorking(true);
    setDownloading(route.endsWith("/download"));
    setError("");
    try {
      setState(await request<State>(route, method, body));
      setToken("");
    } catch (error) {
      if (state) setState(state);
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
      setDownloading(false);
    }
  };
  useEffect(() => {
    if (!downloading) return;
    let active = true;
    const timer = setInterval(() => void request<State>("/updates").then((value) => {
      if (active) setState(value, false);
    }).catch(() => {}), 750);
    return () => { active = false; clearInterval(timer); };
  }, [downloading, setState]);
  return (
    <div className="card updates-panel">
      <h2>О приложении</h2>
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
          {state?.checking || (working && !downloading) ? "Проверка…" : "Проверить обновления"}
        </button>
        <button
          className="outline"
          onClick={() => void window.wiley.openUpdate()}
        >
          Выпуски на GitHub
        </button>
      </div>
      {state && !state.signed && <p className="help">Встроенная установка доступна в сборке с доверенным ключом выпуска.</p>}
      {state?.available && <div>
        <p>Доступна версия {state.available.version}
          {state.available.size ? ` · ${(state.available.size / 1048576).toFixed(1)} МиБ` : ""}
          {state.available.date ? ` · ${state.available.date}` : ""}</p>
        {state.available.notes && <details><summary>История изменений</summary>
          <pre style={{ whiteSpace: "pre-wrap" }}>{state.available.notes}</pre></details>}
        {state.signed && <button disabled={working || state.checking} onClick={() => {
          if (!state.downloaded) void action("/updates/download", "POST");
          else void window.wiley.installUpdate().catch((failure) => setError(failure.message));
        }}>{state.downloaded ? "Установить обновление" : "Скачать обновление"}</button>}
        {downloading && <progress aria-label="Скачивание обновления" max={100} value={state.progress ?? 0} />}
      </div>}
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
      {!state?.signed && <details className="cloud-details">
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
      </details>}
      <p className="help">
        Проверка через 15 секунд после запуска и затем раз в 6 часов. Windows
        уведомляет о каждой версии один раз. Установка обновления запускается
        вами.
      </p>
      <label>
        Срок хранения журнала обновлений
        <select value={state?.retention_days ?? 7} disabled={working || !state}
          onChange={(event) => void action("/updates", "PUT", {
            automatic: state!.automatic, retention_days: Number(event.target.value),
          })}>
          <option value={1}>1 день</option><option value={7}>7 дней</option><option value={30}>30 дней</option>
        </select>
      </label>
      <Feedback />
    </div>
  );
}

function Feedback() {
  const [description, setDescription] = useState("");
  const [preview, setPreview] = useState<Record<string, string>>();
  const [status, setStatus] = useState("");
  return <details className="cloud-details">
    <summary>Сообщить об ошибке</summary>
    <p>Отчёт сохраняется на вашем компьютере. Проверьте описание и удалите из него личные данные.</p>
    <textarea aria-label="Описание проблемы" maxLength={4000} value={description}
      onChange={(event) => { setDescription(event.target.value); setPreview(undefined); setStatus(""); }} />
    <button onClick={() => void request<Record<string, string>>("/feedback/preview", "POST", { description })
      .then(setPreview).catch(() => setStatus("Не удалось подготовить предпросмотр."))}>Предпросмотр отчёта</button>
    {preview && <div>
      {Object.entries(preview).map(([name, content]) => <details key={name}><summary>{name}</summary>
        <pre style={{ whiteSpace: "pre-wrap" }}>{content}</pre></details>)}
      <button onClick={() => void window.wiley.saveFeedback(description)
        .then((saved) => { if (saved) setStatus("Архив сохранён."); })
        .catch(() => setStatus("Не удалось сохранить архив."))}>Сохранить ZIP</button>
    </div>}
    <p role="status">{status}</p>
  </details>;
}
