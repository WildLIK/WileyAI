import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { scopedRequest } from "./api";

type Binding = {
  calendar_id: string;
  name: string;
  timezone: string;
  writable: boolean;
};
type Status = {
  configured: boolean;
  connected: boolean;
  pending: boolean;
  error: string;
  binding: Binding | null;
  auto?: {
    enabled: boolean;
    last_checked: string;
    error: string;
    pending: number;
  };
};
type RemoteCalendar = {
  id: string;
  name: string;
  timezone: string;
  writable: boolean;
};
type Row = {
  id: string;
  action: "import" | "export" | "conflict";
  title: string;
  reason: string;
  starts_at: string;
  local_version?: EventVersion | null;
  google_version?: EventVersion | null;
};
type EventVersion = {
  title: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  all_day: boolean;
  location: string;
  description: string;
  recurrence: {
    rule: string;
    weekdays: number[];
    weekday: number | null;
    until: string | null;
    monthday?: number | null;
    excluded?: string[];
  } | null;
};

function Version({ name, value }: { name: string; value: EventVersion }) {
  const rule = value.recurrence;
  return (
    <div className="google-calendar-version">
      <strong>
        {name}: {value.title}
      </strong>
      <small>
        {new Date(value.starts_at).toLocaleString("ru-RU", {
          timeZone: value.timezone,
        })}{" "}
        —{" "}
        {new Date(value.ends_at).toLocaleString("ru-RU", {
          timeZone: value.timezone,
        })}{" "}
        · {value.timezone}
        {value.all_day && " · весь день, окончание не включается"}
      </small>
      {rule && (
        <small>
          {rule.rule === "daily"
            ? "Ежедневно"
            : rule.rule === "weekdays"
              ? "По будням"
              : rule.rule === "monthly"
                ? rule.monthday === -1
                  ? "Последний день месяца"
                  : "Ежемесячно, число: " +
                    (rule.monthday ?? "как в начале серии")
                : "По дням: " +
                  (rule.weekdays.length ? rule.weekdays : [rule.weekday])
                    .map(
                      (day) =>
                        ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day ?? 0],
                    )
                    .join(", ")}
          {rule.until && " · до " + rule.until}
          {!!rule.excluded?.length &&
            " · исключены даты: " + rule.excluded.join(", ")}
        </small>
      )}
      {value.location && <p>{value.location}</p>}
      {value.description && <p className="note-content">{value.description}</p>}
    </div>
  );
}
type Preview = { ticket: string; rows: Row[]; skipped: string[] };
type Result = { id: string; title: string; ok: boolean; message: string };

export function GoogleCalendarPanel({
  conversationId,
  start,
  end,
  onChanged,
}: {
  conversationId: string;
  start: string;
  end: string;
  onChanged: () => void;
}) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [status, setStatus] = useState<Status | null>(null);
  const [calendars, setCalendars] = useState<RemoteCalendar[]>([]);
  const [selected, setSelected] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [choices, setChoices] = useState<
    Record<string, "google" | "local" | "">
  >({});
  const [results, setResults] = useState<Result[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const identity = conversationId + "|" + start + "|" + end;
  const current = useRef(identity);
  current.current = identity;
  const valid = () => mounted.current && current.current === identity;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const refresh = useCallback(async () => {
    const next = await request<Status>("/calendar/google/status");
    if (mounted.current && current.current === identity) {
      setStatus(next);
      setSelected(next.binding?.calendar_id ?? "");
    }
  }, [request, identity]);
  useEffect(() => {
    void refresh().catch((err) => {
      if (valid()) setError(String(err));
    });
  }, [refresh]);
  useEffect(() => {
    const focus = () =>
      void refresh().catch((err) => {
        if (valid()) setError(String(err));
      });
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [refresh]);
  useEffect(() => {
    const changed = () => {
      setPreview(null);
      setChoices({});
      setResults([]);
      void refresh().catch((err) => setError(String(err)));
    };
    window.addEventListener("wiley-data-updated", changed);
    return () => window.removeEventListener("wiley-data-updated", changed);
  }, [refresh]);
  useEffect(() => {
    if (!status?.pending) return;
    const id = setInterval(() => {
      void refresh().catch((err) => setError(String(err)));
    }, 2000);
    return () => clearInterval(id);
  }, [status?.pending, refresh]);
  useEffect(() => {
    setPreview(null);
    setChoices({});
    setResults([]);
  }, [start, end, conversationId]);
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      if (valid()) setError(String(err));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <section
      className="card google-calendar"
      aria-label="Подключение Google Calendar"
    >
      <h2>Google Calendar</h2>
      <p>
        Выберите календарь для этого пространства. Перенос выполняется вручную,
        только для отмеченных событий. При изменениях с обеих сторон выберите
        нужную версию.
      </p>
      <p className="help">
        События Google из повторяющихся серий импортируются отдельными
        вхождениями за выбранные 7 дней; их правки выполняются в Google.
        Локальная серия отправляется целиком. Удаления и приглашения участникам
        не отправляются. Напоминания WileyAI остаются локальными. До 100
        связанных событий на календарь.
      </p>
      {!status ? (
        <p role="status">Проверяю подключение…</p>
      ) : (
        <>
          <p role="status">
            {status.pending
              ? "Ожидаю вход в браузере…"
              : status.connected
                ? "Аккаунт подключён"
                : "Аккаунт не подключён"}
            {status.binding
              ? " · " + status.binding.name + " · " + status.binding.timezone
              : ""}
          </p>
          {!status.connected && (
            <details>
              <summary>Настроить доступ Google</summary>
              <p>
                В Google Cloud включите Calendar API, создайте OAuth client ID
                типа Desktop app и скачайте JSON. Для приложения в режиме
                Testing добавьте свой адрес в Test users. Затем загрузите JSON
                здесь и войдите через браузер.
              </p>
              <p className="help">
                Нужны доступ к событиям и чтение списка календарей. Ключи
                хранятся в системном хранилище Windows и не входят в резервные
                копии. Не загружайте сюда ключ сервисного аккаунта.
              </p>
              <label>
                JSON клиента Google Desktop app
                <input
                  type="file"
                  accept="application/json,.json"
                  disabled={busy || status.pending}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (!file) return;
                    void run(async () => {
                      if (file.size > 16384)
                        throw new Error("JSON клиента превышает 16 КБ");
                      await request("/calendar/google/client", "PUT", {
                        document: await file.text(),
                      });
                      setPreview(null);
                      await refresh();
                    });
                  }}
                />
              </label>
            </details>
          )}
          {status.configured && (
            <p className="help">
              JSON OAuth-клиента сохранён. Повторно выбирать файл не нужно.
            </p>
          )}
          <div className="button-row">
            <button
              type="button"
              className="subtle"
              disabled={busy}
              onClick={() => void run(refresh)}
            >
              Обновить статус Google
            </button>
            {!status.connected && !status.pending && (
              <button
                type="button"
                className="outline"
                disabled={busy || !status.configured}
                onClick={() =>
                  void run(async () => {
                    await window.wiley.googleCalendarLogin();
                    await refresh();
                  })
                }
              >
                Войти через Google
              </button>
            )}
            {status.pending && (
              <button
                type="button"
                className="outline"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await request("/calendar/google/cancel", "POST");
                    await refresh();
                  })
                }
              >
                Отменить вход
              </button>
            )}
            {status.connected && (
              <>
                <button
                  type="button"
                  className="outline"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      setCalendars(
                        await request<RemoteCalendar[]>(
                          "/calendar/google/calendars",
                        ),
                      );
                    })
                  }
                >
                  Загрузить список календарей
                </button>
                <button
                  type="button"
                  className="subtle"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await request("/calendar/google/disconnect", "POST");
                      setCalendars([]);
                      setPreview(null);
                      setResults([]);
                      await refresh();
                    })
                  }
                >
                  Отключить Google на этом компьютере
                </button>
              </>
            )}
          </div>
          {status.error && <p role="alert">{status.error}</p>}
          {!!calendars.length && (
            <div className="button-row">
              <label>
                Календарь Google
                <select
                  disabled={busy}
                  value={selected}
                  onChange={(event) => setSelected(event.target.value)}
                >
                  <option value="">Выберите календарь</option>
                  {calendars.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} · {item.timezone}
                      {item.writable ? "" : " · только чтение"}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="outline"
                disabled={busy || !selected}
                onClick={() =>
                  void run(async () => {
                    await request("/calendar/google/binding", "PUT", {
                      calendar_id: selected,
                    });
                    setPreview(null);
                    await refresh();
                  })
                }
              >
                Использовать в этом пространстве
              </button>
            </div>
          )}
          {status.connected && status.binding && (
            <button
              type="button"
              className="outline"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  setPreview(null);
                  setChoices({});
                  setResults([]);
                  const next = await request<Preview>(
                    "/calendar/google/preview",
                    "POST",
                    { start, end },
                  );
                  if (valid()) setPreview(next);
                })
              }
            >
              Посмотреть изменения за выбранные 7 дней
            </button>
          )}
          {preview && (
            <div>
              <p className="help">
                Связанные события вне этих дат тоже проверяются. Выберите до 20
                изменений. Конфликт требует выбора версии; ничего не отмечено
                автоматически.
              </p>
              {!preview.rows.length && <p>Новых изменений нет.</p>}
              {!!preview.rows.length && (
                <div className="google-calendar-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Событие</th>
                        <th>Изменение</th>
                        <th>Перенести</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.rows.map((row) => (
                        <tr key={row.id}>
                          <td>
                            {row.title}
                            <small>
                              {new Date(row.starts_at).toLocaleString("ru-RU")}
                              {row.reason && " · " + row.reason}
                            </small>
                            {(row.local_version || row.google_version) && (
                              <details>
                                <summary>Сравнить версии события</summary>
                                {row.local_version && (
                                  <Version
                                    name="WileyAI"
                                    value={row.local_version}
                                  />
                                )}
                                {row.google_version && (
                                  <Version
                                    name="Google"
                                    value={row.google_version}
                                  />
                                )}
                              </details>
                            )}
                          </td>
                          <td>
                            {row.action === "import"
                              ? "Из Google в WileyAI"
                              : row.action === "export"
                                ? "Из WileyAI в Google"
                                : "Обе версии изменились"}
                          </td>
                          <td>
                            <select
                              aria-label={"Перенести «" + row.title + "»"}
                              disabled={busy}
                              value={choices[row.id] || ""}
                              onChange={(event) =>
                                setChoices({
                                  ...choices,
                                  [row.id]: event.target.value as
                                    "google" | "local" | "",
                                })
                              }
                            >
                              <option value="">Пропустить</option>
                              {row.action !== "export" && (
                                <option value="google">Взять Google</option>
                              )}
                              {row.action !== "import" && (
                                <option value="local">Взять WileyAI</option>
                              )}
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {preview.skipped.map((message, index) => (
                <p className="help" key={index}>
                  {message}
                </p>
              ))}
              {!!preview.rows.length && (
                <button
                  type="button"
                  className="primary"
                  disabled={
                    busy ||
                    Object.values(choices).filter(Boolean).length === 0 ||
                    Object.values(choices).filter(Boolean).length > 20
                  }
                  onClick={() =>
                    void run(async () => {
                      const result = await request<{ results: Result[] }>(
                        "/calendar/google/apply",
                        "POST",
                        {
                          ticket: preview.ticket,
                          choices: Object.entries(choices)
                            .filter(([, direction]) => direction)
                            .map(([id, direction]) => ({ id, direction })),
                        },
                      );
                      if (valid()) {
                        setResults(result.results);
                        setPreview(null);
                        setChoices({});
                        onChanged();
                      }
                    })
                  }
                >
                  Перенести выбранные события (
                  {Object.values(choices).filter(Boolean).length})
                </button>
              )}
            </div>
          )}
        </>
      )}
      {busy && (
        <p role="status" className="loading">
          Обмениваюсь данными с Google…
        </p>
      )}
      {status?.binding && (
        <div className="card">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={!!status.auto?.enabled}
              disabled={busy}
              onChange={(event) => {
                const enabled = event.target.checked;
                void run(async () => {
                  await request("/calendar/google/auto", "PUT", { enabled });
                  await refresh();
                });
              }}
            />
            Автоматически читать изменения Google каждые 5 минут
          </label>
          <p className="help">
            Новые события и изменения без локального конфликта импортируются в
            WileyAI. Правки из WileyAI и конфликты переносятся вручную.
            Работает, пока приложение запущено.
          </p>
          {status.auto?.last_checked && (
            <p>
              Проверено:{" "}
              {new Date(status.auto.last_checked).toLocaleString("ru-RU")} ·
              ожидает просмотра: {status.auto.pending}
            </p>
          )}
          {status.auto?.error && <p role="alert">{status.auto.error}</p>}
          <button
            className="outline"
            disabled={busy}
            onClick={() => void run(refresh)}
          >
            Обновить состояние синхронизации
          </button>
        </div>
      )}
      {results.map((result) => (
        <p key={result.id} role={result.ok ? "status" : "alert"}>
          {result.title}: {result.message}
        </p>
      ))}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
