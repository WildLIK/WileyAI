import { useEffect, useState } from "react";
import { request } from "./api";

type State = {
  items: {
    id: string;
    name: string;
    description: string;
    size: string;
    installed: boolean;
    available: boolean;
    restart: boolean;
  }[];
  job: {
    component: string;
    state: string;
    stage: string;
    progress: number | null;
  } | null;
};

export function ComponentPanel({
  onReady,
  ids,
  expanded = false,
}: {
  onReady: () => void;
  ids?: string[];
  expanded?: boolean;
}) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const [open, setOpen] = useState(expanded);
  useEffect(() => {
    let active = true;
    let first = true;
    const load = async () => {
      try {
        const next = await request<State>("/components");
        if (!active) return;
        setState(next);
        if (first)
          setOpen(
            expanded ||
              !next.items.some((item) => item.installed) ||
              next.job?.state === "running",
          );
        first = false;
      } catch (error) {
        if (active) setError(String(error));
      }
    };
    void load();
    const timer = setInterval(load, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  const action = async (work: () => Promise<unknown>) => {
    setWorking(true);
    setError("");
    try {
      await work();
      setState(await request<State>("/components"));
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  };
  const installing = state?.job?.state === "running";
  const items =
    state?.items.filter((item) => !ids || ids.includes(item.id)) ?? [];
  return (
    <details
      className="component-panel"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        Компоненты{" "}
        {state && (
          <small>
            · {items.filter((item) => item.installed).length} из {items.length}{" "}
            установлено
            {installing ? " · идёт установка" : ""}
          </small>
        )}
      </summary>
      <p className="help">
        Для локальных моделей сначала установите движок, затем скачайте модель в
        категории ниже. Для облачных API эти компоненты не нужны.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="component-list">
        {items.map((item) => (
          <div className="component-row" key={item.id}>
            <div>
              <strong>{item.name}</strong>
              <span>{item.description}</span>
              <small>
                {item.installed
                  ? item.restart
                    ? "Установлено · нужен перезапуск"
                    : "Готово"
                  : item.size}
              </small>
            </div>
            {item.restart ? (
              <button
                className="outline"
                disabled={working || installing}
                onClick={() => action(() => window.wiley.restart())}
              >
                Перезапустить
              </button>
            ) : item.id === "ollama" && item.installed ? (
              <button
                className="outline"
                disabled={working || installing}
                onClick={() =>
                  action(async () => {
                    await window.wiley.startOllama();
                    onReady();
                  })
                }
              >
                Запустить движок
              </button>
            ) : (
              <button
                className="outline"
                disabled={working || installing || item.installed}
                onClick={() =>
                  action(() =>
                    request(`/components/${item.id}/install`, "POST"),
                  )
                }
              >
                {item.installed ? "Установлено" : "Установить"}
              </button>
            )}
          </div>
        ))}
      </div>
      {state?.job && (
        <div className="component-job" role="status" aria-live="polite">
          <span>
            {state.items.find((item) => item.id === state.job!.component)?.name}
            : {state.job.stage}
          </span>
          {installing && (
            <>
              <progress
                aria-label="Установка компонента"
                max={100}
                value={state.job.progress ?? undefined}
              />
              <button
                className="outline"
                disabled={working}
                onClick={() =>
                  action(() => request("/components/cancel", "POST"))
                }
              >
                Отменить установку
              </button>
            </>
          )}
        </div>
      )}
      <p className="help">
        Модели и компоненты хранятся отдельно от программы и сохраняются при её
        обновлении. Загрузка запускается только по нажатию «Установить».
      </p>
    </details>
  );
}
