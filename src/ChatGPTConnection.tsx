import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { request } from "./api";

type Connection = {
  connection_id: string;
  connected: boolean;
  plan_enabled: boolean;
  email: string;
  pending: boolean;
  error: string;
  registration_pending?: boolean;
  diagnostic?: {
    stage?: string;
    code?: string;
    http_status?: number;
    request_id?: string;
  };
};
type Model = { id: string; name: string };

export function ChatGPTConnection({
  model,
  connectionId,
  onSelect,
  onConnected,
}: {
  model: string;
  connectionId: string;
  onSelect: (connection: string, model: string) => void;
  onConnected: (connection: string, model: string) => Promise<void>;
}) {
  const [state, setState] = useState<Connection | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [welcome, setWelcome] = useState(false);
  const awaiting = useRef(false);
  const mounted = useRef(false);
  const current = useRef({ model, connectionId, onSelect, onConnected });
  current.current = { model, connectionId, onSelect, onConnected };

  const load = useCallback(async (catalog = false) => {
    const value = await request<Connection>("/chatgpt/status");
    if (!mounted.current) return;
    setState(value);
    if (value.pending) awaiting.current = true;
    if (
      value.connected &&
      value.plan_enabled &&
      !value.pending &&
      !value.error &&
      (catalog || awaiting.current)
    ) {
      const result = await request<{ models: Model[] }>("/chatgpt/models");
      if (!mounted.current) return;
      setModels(result.models);
      if (localStorage.getItem("wiley-chatgpt-plan-notice") !== "seen")
        setWelcome(true);
      const selected =
        result.models.find((item) => item.id === current.current.model)?.id ||
        result.models[0]?.id;
      if (!selected) {
        setError(
          "Аккаунт подключён, но доступных моделей пока нет. Проверьте разрешения и лимиты плана ChatGPT.",
        );
        return;
      }
      if (
        awaiting.current ||
        !current.current.connectionId ||
        !current.current.model
      ) {
        awaiting.current = false;
        current.current.onSelect(value.connection_id, selected);
        await current.current.onConnected(value.connection_id, selected);
      } else if (selected !== current.current.model) {
        current.current.onSelect(value.connection_id, selected);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load(true).catch(
      (e) => mounted.current && setError(String(e.message || e)),
    );
    return () => {
      mounted.current = false;
    };
  }, [load]);

  useEffect(() => {
    if (!state?.pending) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        await load();
      } catch (e) {
        if (active) setError(String(e instanceof Error ? e.message : e));
      }
      if (active) timer = setTimeout(tick, 1500);
    };
    timer = setTimeout(tick, 1500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [state?.pending, load]);

  async function action(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <div className="chatgpt-connection">
      <p>
        Используйте свой аккаунт ChatGPT и доступные лимиты подписки. API-ключ
        не нужен. Распознавание речи и озвучка остаются в WileyAI.
      </p>
      <p role="status">
        {state?.pending
          ? "Завершите вход и разрешите использование плана в открывшемся браузере…"
          : state?.connected
            ? `Подключён ChatGPT${state.email ? ": " + state.email : ""}${state.plan_enabled ? "" : " · использование плана не разрешено"}`
            : state?.registration_pending
              ? "WileyAI зарегистрирован в ChatGPT, но вход ещё не завершён"
              : "Аккаунт ChatGPT не подключён"}
      </p>
      <div className="button-row">
        {state?.connected && (
          <button
            className="outline"
            onClick={() => action(() => window.wiley.chatgptUsage())}
          >
            Управлять лимитами ChatGPT
          </button>
        )}
        <button
          className="outline"
          disabled={busy || state?.pending}
          onClick={() =>
            action(async () => {
              awaiting.current = true;
              await window.wiley.chatgptLogin();
              await load();
            })
          }
        >
          Continue with ChatGPT
        </button>
        {state?.pending && (
          <button
            className="outline"
            disabled={busy}
            onClick={() =>
              action(async () => {
                awaiting.current = false;
                await request("/chatgpt/cancel", "POST");
                await load();
              })
            }
          >
            Отменить вход
          </button>
        )}
        {state?.connected && (
          <>
            <button
              className="outline"
              disabled={busy || state.pending}
              onClick={() =>
                action(async () => {
                  awaiting.current = true;
                  await window.wiley.chatgptLogin(true);
                  await load();
                })
              }
            >
              Другой аккаунт
            </button>
            <button
              className="outline"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  awaiting.current = false;
                  await request("/chatgpt/logout", "POST");
                  setModels([]);
                  await load();
                })
              }
            >
              Отключить ChatGPT
            </button>
          </>
        )}
        <button
          className="outline"
          disabled={busy || state?.pending}
          onClick={() => action(() => load(true))}
        >
          Проверить подключение
        </button>
      </div>
      {models.length > 0 && state?.connected && (
        <label>
          Модель ChatGPT
          <select
            aria-label="Модель ChatGPT"
            disabled={busy || state.pending}
            value={model}
            onChange={(e) => onSelect(state.connection_id, e.target.value)}
          >
            {models.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {(error || state?.error) && (
        <p className="error" role="alert">
          {error || state?.error}
        </p>
      )}
      {state?.error && state.diagnostic?.code && (
        <p className="help">
          Код ошибки: {state.diagnostic.code}
          {state.diagnostic.http_status
            ? ` · HTTP ${state.diagnostic.http_status}`
            : ""}
          {state.diagnostic.request_id
            ? ` · запрос ${state.diagnostic.request_id}`
            : ""}
        </p>
      )}
      <p className="help">
        Запросы используют общие лимиты плана ChatGPT. История и память ведутся
        в WileyAI. Доступность моделей определяется аккаунтом.
      </p>
      {welcome &&
        createPortal(
          <div className="space-dialog-backdrop">
            <section
              className="space-dialog card"
              role="dialog"
              aria-modal="true"
              aria-label="Используется план ChatGPT"
            >
              <h2>Вы используете план ChatGPT</h2>
              <p>
                Ответы ChatGPT в WileyAI используют доступные лимиты вашего
                плана. Их можно посмотреть и изменить в настройках использования
                ChatGPT.
              </p>
              <div className="button-row">
                <button
                  autoFocus
                  onClick={() => {
                    localStorage.setItem("wiley-chatgpt-plan-notice", "seen");
                    setWelcome(false);
                  }}
                >
                  Понятно
                </button>
                <button
                  className="outline"
                  onClick={() => action(() => window.wiley.chatgptUsage())}
                >
                  Управлять лимитами
                </button>
              </div>
            </section>
          </div>,
          document.body,
        )}
    </div>
  );
}
