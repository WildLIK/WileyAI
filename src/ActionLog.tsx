import { useEffect, useState } from "react";
import { request } from "./api";

type Entry = {
  id: string;
  kind: string;
  target: string;
  status: string;
  created: string;
  details: { text?: string; pid?: number; executable?: string };
};
const labels: Record<string, string> = {
  process_started: "Процесс подтверждён",
  already_running: "Процесс уже работает",
  dispatched: "Запрос передан, процесс не подтверждён",
  launched: "Запрос передан",
  confirmed: "Плеер подтвердил",
  unconfirmed: "Не подтверждено",
  ok: "Выполнено",
  error: "Ошибка",
  preview: "Только проверка",
  connected: "Плеер подключён",
  ambiguous: "Нужно уточнение",
};
export function ActionLog() {
  const [items, setItems] = useState<Entry[]>([]);
  const [error, setError] = useState("");
  const load = async () => {
    try {
      setItems(
        (await request<Entry[]>("/actions")).filter(
          (item) => item.kind !== "plan",
        ),
      );
      setError("");
    } catch (reason) {
      setError(String(reason));
    }
  };
  useEffect(() => {
    void load();
    const changed = () => void load();
    window.addEventListener("wiley-data-updated", changed);
    return () => window.removeEventListener("wiley-data-updated", changed);
  }, []);
  return (
    <section className="card action-log" aria-label="Журнал действий Windows">
      <div className="application-discovery-heading">
        <div>
          <h2>Журнал действий Windows</h2>
          <p className="help">
            Результаты инструментов: запуск процесса, передача запроса или
            ошибка. Ответ модели сам по себе не создаёт запись.
          </p>
        </div>
        <button className="outline" onClick={() => void load()}>
          Обновить журнал
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {!items.length && <p className="help">Действий пока нет.</p>}
      <div className="action-log-entries">
        {items
          .slice(-20)
          .reverse()
          .map((item) => (
            <details
              key={item.id}
              className={item.status === "error" ? "action-error" : ""}
            >
              <summary>
                <time>{new Date(item.created).toLocaleString("ru-RU")}</time>
                <strong>{labels[item.status] || item.status}</strong>
                <span>
                  {item.kind} · {item.target}
                </span>
              </summary>
              <p>
                {item.details.text ||
                  "Дополнительные сведения отсутствуют у этой старой записи."}
              </p>
              {item.details.pid && <small>PID: {item.details.pid}</small>}
            </details>
          ))}
      </div>
    </section>
  );
}
