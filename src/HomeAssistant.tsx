import { useEffect, useMemo, useRef, useState } from "react";
import { scopedRequest, errorText } from "./api";

type Binding = { revision: string; enabled: boolean; entities: string[] };
type Status = {
  configured: boolean;
  url: string;
  name: string;
  version: string;
  checked_at: string;
  epoch: string;
  binding: Binding;
};
type Entity = {
  entity_id: string;
  name: string;
  domain: string;
  state: string;
  unit: string;
  attributes: Record<string, unknown>;
  actions: string[];
};
type Preview = {
  ticket: string;
  device: Entity;
  label: string;
  value: number | null;
  expected: Record<string, unknown>;
  already: boolean;
};
type Receipt = {
  id: string;
  label: string;
  entity_id: string;
  action: { action: string; value: number | null };
  state: string;
  text: string;
  created: string;
};
const labels: Record<string, string> = {
  on: "Включить",
  off: "Выключить",
  brightness: "Яркость",
  speed: "Скорость",
};
const stateLabel = (value: string) =>
  ({
    on: "Включено",
    off: "Выключено",
    unavailable: "Недоступно",
    unknown: "Неизвестно",
  })[value] || value;
const when = (value: string) =>
  value ? new Date(value).toLocaleString("ru-RU") : "—";

export function HomeAssistantPanel({
  conversationId,
  scopeName,
}: {
  conversationId: string;
  scopeName: string;
}) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [status, setStatus] = useState<Status | null>(null);
  const [url, setUrl] = useState(""),
    [token, setToken] = useState("");
  const [entities, setEntities] = useState<Entity[]>([]),
    [checkedAt, setCheckedAt] = useState("");
  const [selected, setSelected] = useState<string[]>([]),
    [enabled, setEnabled] = useState(false);
  const [query, setQuery] = useState(""),
    [domain, setDomain] = useState("");
  const [percent, setPercent] = useState(50);
  const [preview, setPreview] = useState<Preview | null>(null),
    [confirmed, setConfirmed] = useState(false);
  const [history, setHistory] = useState<Receipt[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const mounted = useRef(true),
    working = useRef(false);
  const review = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (preview) review.current?.scrollIntoView({ block: "nearest" });
  }, [preview]);
  const reads = useRef(new AbortController());
  const apply = (value: Status) => {
    setStatus(value);
    setUrl(value.url);
    setSelected(value.binding.entities);
    setEnabled(value.binding.enabled);
    setPreview(null);
    setConfirmed(false);
  };
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    reads.current = controller;
    void request<Status>(
      "/home-assistant/status",
      "GET",
      undefined,
      controller.signal,
    )
      .then(async (value) => {
        if (controller.signal.aborted) return;
        apply(value);
        if (value.configured) {
          const [rows, actions] = await Promise.all([
            request<{ entities: Entity[]; checked_at: string }>(
              "/home-assistant/entities",
              "GET",
              undefined,
              controller.signal,
            ),
            request<Receipt[]>(
              "/home-assistant/actions",
              "GET",
              undefined,
              controller.signal,
            ),
          ]);
          if (!controller.signal.aborted) {
            setEntities(rows.entities);
            setCheckedAt(rows.checked_at);
            setHistory(actions);
          }
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorText(err));
      });
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, [request]);
  async function run(action: () => Promise<void>) {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      if (mounted.current) {
        setError(errorText(err));
        setPreview(null);
        setConfirmed(false);
      }
    } finally {
      working.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function refresh() {
    const [value, rows, actions] = await Promise.all([
      request<Status>("/home-assistant/status"),
      request<{ entities: Entity[]; checked_at: string }>(
        "/home-assistant/entities",
      ),
      request<Receipt[]>("/home-assistant/actions"),
    ]);
    if (mounted.current) {
      apply(value);
      setEntities(rows.entities);
      setCheckedAt(rows.checked_at);
      setHistory(actions);
    }
  }
  const dirty =
    status &&
    (enabled !== status.binding.enabled ||
      JSON.stringify([...selected].sort()) !==
        JSON.stringify([...status.binding.entities].sort()));
  const found = entities.filter(
    (row) =>
      (!domain || row.domain === domain) &&
      (row.name + " " + row.entity_id)
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  );
  return (
    <section className="page scroll-page home-page">
      <h1>Интеграции</h1>
      <p>
        Home Assistant · {scopeName}. Выберите устройства для этого
        пространства, затем разрешите управление.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="card">
        <h2>Home Assistant</h2>
        <p>
          {status?.configured
            ? `Подключение сохранено: ${status.name} · ${status.url} · ${status.version}. Проверка при сохранении: ${when(status.checked_at)}.`
            : "Home Assistant не подключён"}
        </p>
        <details open={!status?.configured}>
          <summary>Адрес и токен сервера</summary>
          <p>
            В Home Assistant откройте свой профиль → Безопасность → Долгосрочные
            токены доступа. Создайте токен для WileyAI и вставьте его здесь.
            Сохранённый токен хранится в системном хранилище Windows.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const credential = token;
              setToken("");
              void run(async () => {
                const value = await request<Status>(
                  "/home-assistant/connection",
                  "PUT",
                  { url, token: credential },
                );
                if (mounted.current) {
                  apply(value);
                  setEntities([]);
                  setHistory([]);
                  setCheckedAt("");
                  setNotice(
                    "Home Assistant ответил. Подключение сохранено; выберите устройства ниже.",
                  );
                }
                await refresh();
              });
            }}
          >
            <label>
              Адрес Home Assistant
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="http://homeassistant.local:8123"
                maxLength={1000}
                required
                disabled={busy}
              />
            </label>
            <label>
              Токен Home Assistant
              <input
                type="password"
                autoComplete="off"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                maxLength={8192}
                required
                disabled={busy}
              />
            </label>
            <button disabled={busy || !token.trim()}>
              Проверить и сохранить подключение
            </button>
          </form>
        </details>
        {status?.configured && (
          <div className="home-actions">
            <button
              className="outline"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const value = await request<Status>(
                    "/home-assistant/check",
                    "POST",
                  );
                  if (mounted.current)
                    setNotice(
                      `Сервер ответил: ${value.name}, проверено ${when(value.checked_at)}.`,
                    );
                  await refresh();
                })
              }
            >
              Проверить соединение
            </button>
            <button
              className="outline"
              disabled={busy}
              onClick={() => void run(refresh)}
            >
              Обновить устройства
            </button>
            <button
              className="outline"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const value = await request<Status>(
                    "/home-assistant/connection",
                    "DELETE",
                  );
                  if (mounted.current) {
                    apply(value);
                    setEntities([]);
                    setHistory([]);
                    setCheckedAt("");
                    setNotice(
                      "Подключение удалено из WileyAI. При необходимости отзовите токен в Home Assistant.",
                    );
                  }
                })
              }
            >
              Отключить Home Assistant
            </button>
          </div>
        )}
      </div>
      {status?.configured && (
        <>
          <div className="card">
            <h2>Доступ к устройствам</h2>
            <p>
              Свет, выключатели и вентиляторы поддерживают управление. Остальные
              показанные устройства доступны для чтения. Состояние подтверждает
              сервер Home Assistant. Последнее чтение: {when(checkedAt)}.
            </p>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={enabled}
                disabled={busy}
                onChange={(event) => {
                  setEnabled(event.target.checked);
                  setPreview(null);
                }}
              />
              Разрешить управление выбранными устройствами в этом пространстве
            </label>
            <div className="home-actions">
              <button
                disabled={busy || !dirty}
                onClick={() =>
                  void run(async () => {
                    const value = await request<Status>(
                      "/home-assistant/access",
                      "PUT",
                      {
                        enabled,
                        entities: selected,
                        expected_revision: status.binding.revision,
                      },
                    );
                    if (mounted.current) {
                      apply(value);
                      setNotice("Доступ сохранён для текущего пространства.");
                    }
                  })
                }
              >
                Сохранить доступ ({selected.length}/100)
              </button>
            </div>
            {dirty && <p>Сначала сохраните изменения доступа.</p>}
            <div className="home-filters">
              <label>
                Найти устройство
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  maxLength={160}
                />
              </label>
              <label>
                Тип устройства
                <select
                  value={domain}
                  onChange={(event) => setDomain(event.target.value)}
                >
                  <option value="">Все типы</option>
                  {[...new Set(entities.map((row) => row.domain))]
                    .sort()
                    .map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                </select>
              </label>
              <label>
                Яркость или скорость, %
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={percent}
                  onChange={(event) => {
                    setPercent(Number(event.target.value));
                    setPreview(null);
                  }}
                />
              </label>
            </div>
            <p>
              Показано: {found.length} из {entities.length}. Для голоса выберите
              узнаваемые названия в Home Assistant.
            </p>
            <div className="home-entities">
              {found.map((row) => (
                <article className="home-entity" key={row.entity_id}>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      aria-label={`Выбрать ${row.name} (${row.entity_id})`}
                      checked={selected.includes(row.entity_id)}
                      disabled={
                        busy ||
                        (!selected.includes(row.entity_id) &&
                          selected.length >= 100)
                      }
                      onChange={(event) => {
                        setSelected(
                          event.target.checked
                            ? [...selected, row.entity_id]
                            : selected.filter((id) => id !== row.entity_id),
                        );
                        setPreview(null);
                      }}
                    />
                    <strong>{row.name}</strong>
                  </label>
                  <small>{row.entity_id}</small>
                  <p>
                    {stateLabel(row.state)} {row.unit}
                    {typeof row.attributes.brightness === "number" &&
                    row.state === "on"
                      ? ` · Яркость ${Math.round((row.attributes.brightness * 100) / 255)}%`
                      : ""}
                    {typeof row.attributes.percentage === "number"
                      ? ` · Скорость ${row.attributes.percentage}%`
                      : ""}
                  </p>
                  <div className="home-actions">
                    {row.actions.map((action) => (
                      <button
                        key={action}
                        className="outline"
                        disabled={
                          busy ||
                          !!dirty ||
                          !status.binding.enabled ||
                          !status.binding.entities.includes(row.entity_id) ||
                          !Number.isInteger(percent) ||
                          percent < 0 ||
                          percent > 100
                        }
                        onClick={() =>
                          void run(async () => {
                            const value = await request<Preview>(
                              "/home-assistant/preview",
                              "POST",
                              {
                                entity_id: row.entity_id,
                                action,
                                ...(action === "brightness" ||
                                action === "speed"
                                  ? { value: percent }
                                  : {}),
                              },
                            );
                            if (mounted.current) {
                              setPreview(value);
                              setConfirmed(false);
                            }
                          })
                        }
                      >
                        {labels[action]}
                        {action === "brightness" || action === "speed"
                          ? ` ${percent}%`
                          : ""}
                      </button>
                    ))}
                  </div>
                  {!row.actions.length && (
                    <small>Только чтение или устройство недоступно</small>
                  )}
                </article>
              ))}
            </div>
          </div>
          {preview && (
            <div
              className="card home-preview"
              ref={review}
              role="region"
              aria-label="Подтверждение умного дома"
            >
              <h2>Проверьте действие</h2>
              <p>
                <strong>{preview.device.name}</strong> ·{" "}
                {preview.device.entity_id}
              </p>
              <p>
                Сейчас: {stateLabel(preview.device.state)}. Действие:{" "}
                {preview.label}
                {preview.value !== null ? ` ${preview.value}%` : ""}.
              </p>
              {preview.already && (
                <p>
                  Состояние уже соответствует запросу. Повторная команда не
                  потребуется.
                </p>
              )}
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={confirmed}
                  disabled={busy}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                Подтверждаю устройство и действие
              </label>
              <div className="home-actions">
                <button
                  disabled={busy || !confirmed}
                  onClick={() =>
                    void run(async () => {
                      // Confirmed writes continue on the server when navigating away.
                      const receipt = await request<Receipt>(
                        "/home-assistant/confirm",
                        "POST",
                        { ticket: preview.ticket, confirmed: true },
                      );
                      if (mounted.current) {
                        setPreview(null);
                        setConfirmed(false);
                        setNotice(receipt.text);
                        await refresh();
                      }
                    })
                  }
                >
                  Подтвердить действие
                </button>
                <button
                  className="outline"
                  disabled={busy}
                  onClick={() => {
                    setPreview(null);
                    setConfirmed(false);
                  }}
                >
                  Отмена
                </button>
              </div>
            </div>
          )}
          <div className="card">
            <h2>Последние действия Home Assistant</h2>
            <p>
              Переход между вкладками не отменяет уже отправленную команду. При
              потере ответа проверяйте результат здесь.
            </p>
            {history.length === 0 && (
              <p>Действий в этом пространстве пока нет.</p>
            )}
            {history.map((row) => (
              <article className="home-entity" key={row.id}>
                <strong>
                  {row.label} · {labels[row.action.action]}
                  {row.action.value !== null ? ` ${row.action.value}%` : ""}
                </strong>
                <small>
                  {row.entity_id} · {when(row.created)}
                </small>
                <p>{row.text}</p>
                {row.state === "unknown" && (
                  <button
                    className="outline"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const receipt = await request<Receipt>(
                          `/home-assistant/actions/${row.id}/check`,
                          "POST",
                        );
                        if (mounted.current) setNotice(receipt.text);
                        await refresh();
                      })
                    }
                  >
                    Проверить результат без повтора
                  </button>
                )}
              </article>
            ))}
          </div>
          <div className="card">
            <h2>В чате и голосом</h2>
            <p>
              «Умный дом, включи Кухня» · «Умный дом, выключи Кухня» · «Умный
              дом, яркость Кухня на 30» · «Умный дом, скорость Вентилятор на 50»
              · «Проверь умный дом».
            </p>
            <p>
              Сначала WileyAI покажет устройство и действие. Для выполнения
              скажите «подтверждаю умный дом». Для отмены — «отмена умный дом».
            </p>
          </div>
        </>
      )}
    </section>
  );
}
