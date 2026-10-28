import { memo, useEffect, useMemo, useRef, useState } from "react";
import { scopedRequest, errorText } from "./api";
type Status = {
  configured: boolean;
  connected: boolean;
  account: string;
  pending: boolean;
  password_required: boolean;
  revision?: string;
};
type Dialog = { ticket: string; title: string; unread: number };
type Message = {
  id: number;
  text: string;
  date: string;
  outgoing: boolean;
  media: boolean;
};
type Outbox = {
  id: string;
  state: string;
  message_id: number;
  created: string;
  title: string;
  text: string;
};
type Preview = {
  ticket: string;
  recipient: string;
  text: string;
  retry?: boolean;
};
export const TelegramPanel = memo(function TelegramPanel({
  conversationId,
  visible,
}: {
  conversationId: string;
  visible: boolean;
}) {
  const [visited, setVisited] = useState(false);
  useEffect(() => {
    if (visible) setVisited(true);
  }, [visible]);
  if (!visible && !visited) return null;
  return (
    <div style={{ display: visible ? "contents" : "none" }}>
      <TelegramContent
        key={conversationId}
        conversationId={conversationId}
        visible={visible}
      />
    </div>
  );
});
function TelegramContent({
  conversationId,
  visible,
}: {
  conversationId: string;
  visible: boolean;
}) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [status, setStatus] = useState<Status | null>(null),
    [dialogs, setDialogs] = useState<Dialog[]>([]),
    [selected, setSelected] = useState<Dialog | null>(null),
    [messages, setMessages] = useState<Message[]>([]),
    [before, setBefore] = useState(0),
    [outbox, setOutbox] = useState<Outbox[]>([]),
    [text, setText] = useState(""),
    [preview, setPreview] = useState<Preview | null>(null),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [sending, setSending] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [apiId, setApiId] = useState(""),
    [apiHash, setApiHash] = useState(""),
    [phone, setPhone] = useState(""),
    [code, setCode] = useState(""),
    [password, setPassword] = useState("");
  const mounted = useRef(true),
    active = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      active.current?.abort();
    };
  }, [request]);
  const refreshOutbox = async () => {
    const rows = await request<Outbox[]>("/telegram/outbox");
    if (mounted.current) setOutbox(rows);
  };
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    const refresh = () =>
      void request<Status>(
        "/telegram/status",
        "GET",
        undefined,
        controller.signal,
      )
        .then((value) => {
          if (!controller.signal.aborted) setStatus(value);
        })
        .catch((err) => {
          if (!controller.signal.aborted) setError(errorText(err));
        });
    refresh();
    window.addEventListener("focus", refresh);
    return () => {
      controller.abort();
      window.removeEventListener("focus", refresh);
    };
  }, [visible, request]);
  useEffect(() => {
    setPreview(null);
    setConfirmed(false);
  }, [text, selected?.ticket, visible]);
  useEffect(() => {
    setDialogs([]);
    setSelected(null);
    setMessages([]);
    setOutbox([]);
    setText("");
    if (status?.connected)
      void refreshOutbox().catch((err) => setError(errorText(err)));
  }, [status?.connected, status?.account, status?.revision]);
  useEffect(() => {
    if (!visible && !sending) active.current?.abort();
  }, [visible, sending]);
  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action(controller.signal);
    } catch (err) {
      if (mounted.current && !controller.signal.aborted)
        setError(errorText(err));
    } finally {
      if (active.current === controller) active.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  async function loadMessages(
    dialog: Dialog,
    offset = 0,
    signal?: AbortSignal,
  ) {
    const result = await request<{ messages: Message[]; next_before: number }>(
      "/telegram/messages/" + dialog.ticket + "?before=" + offset,
      "GET",
      undefined,
      signal,
    );
    if (mounted.current && !signal?.aborted) {
      setSelected(dialog);
      setMessages(result.messages);
      setBefore(result.next_before);
    }
  }
  return (
    <section className="page scroll-page">
      <h1>Telegram</h1>
      <p>
        Личный аккаунт, выбранные диалоги и сообщения. Отправка выполняется
        только после предпросмотра и подтверждения.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <details className="card mail-connection" open={!status?.connected}>
        <summary>
          Подключение Telegram {status?.connected ? " · " + status.account : ""}
        </summary>
        <p>
          Создайте приложение на my.telegram.org в разделе API development tools
          и укажите его api_id и api_hash. Сессия хранится в хранилище ключей
          Windows; код и пароль входа не сохраняются.
        </p>
        <button
          className="outline"
          disabled={busy}
          onClick={() =>
            void run(async (signal) => {
              const value = await request<Status>(
                "/telegram/status",
                "GET",
                undefined,
                signal,
              );
              if (!signal.aborted) setStatus(value);
            })
          }
        >
          Обновить статус Telegram
        </button>
        {status?.configured && !status.connected && !status.pending && (
          <button
            className="outline"
            disabled={busy}
            onClick={() => setStatus({ ...status, configured: false })}
          >
            Изменить параметры Telegram
          </button>
        )}
        {!status?.connected && (
          <>
            {!status?.configured && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void run(async (signal) => {
                    const value = await request<Status>(
                      "/telegram/client",
                      "PUT",
                      { api_id: Number(apiId), api_hash: apiHash },
                      signal,
                    );
                    if (!signal.aborted) {
                      setStatus(value);
                      setApiHash("");
                    }
                  });
                }}
              >
                <fieldset disabled={busy}>
                  <label>
                    Telegram api_id
                    <input
                      type="number"
                      required
                      value={apiId}
                      onChange={(event) => setApiId(event.target.value)}
                    />
                  </label>
                  <label>
                    Telegram api_hash
                    <input
                      type="password"
                      required
                      autoComplete="off"
                      value={apiHash}
                      onChange={(event) => setApiHash(event.target.value)}
                    />
                  </label>
                  <button className="outline">
                    Сохранить настройки Telegram
                  </button>
                </fieldset>
              </form>
            )}
            {status?.configured && !status.pending && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void run(async (signal) => {
                    const value = await request<Status>(
                      "/telegram/login",
                      "POST",
                      { phone },
                      signal,
                    );
                    if (!signal.aborted) setStatus(value);
                  });
                }}
              >
                <fieldset disabled={busy}>
                  <label>
                    Номер Telegram
                    <input
                      required
                      placeholder="+79991234567"
                      value={phone}
                      onChange={(event) => setPhone(event.target.value)}
                      autoComplete="off"
                    />
                  </label>
                  <button className="outline">Получить код Telegram</button>
                </fieldset>
              </form>
            )}
            {status?.pending && !status.password_required && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const value = code;
                  setCode("");
                  void run(async (signal) => {
                    const result = await request<Status>(
                      "/telegram/code",
                      "POST",
                      { code: value },
                      signal,
                    );
                    if (!signal.aborted) setStatus(result);
                  });
                }}
              >
                <fieldset disabled={busy}>
                  <label>
                    Код Telegram
                    <input
                      required
                      inputMode="numeric"
                      maxLength={8}
                      autoComplete="off"
                      value={code}
                      onChange={(event) => setCode(event.target.value)}
                    />
                  </label>
                  <button className="outline">Подтвердить код Telegram</button>
                </fieldset>
              </form>
            )}
            {status?.password_required && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const value = password;
                  setPassword("");
                  void run(async (signal) => {
                    const result = await request<Status>(
                      "/telegram/password",
                      "POST",
                      { password: value },
                      signal,
                    );
                    if (!signal.aborted) setStatus(result);
                  });
                }}
              >
                <fieldset disabled={busy}>
                  <label>
                    Пароль двухэтапной проверки Telegram
                    <input
                      type="password"
                      autoComplete="off"
                      required
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                    />
                  </label>
                  <button className="outline">Войти в Telegram</button>
                </fieldset>
              </form>
            )}
          </>
        )}
        {(status?.connected || status?.pending) && (
          <button
            className="outline"
            disabled={busy}
            onClick={() =>
              void run(async (signal) =>
                setStatus(
                  await request<Status>(
                    "/telegram/disconnect",
                    "POST",
                    undefined,
                    signal,
                  ),
                ),
              )
            }
          >
            Отключить Telegram в WileyAI
          </button>
        )}
      </details>
      {status?.connected && (
        <>
          <div className="mail-grid">
            <section className="card">
              <h2>Диалоги</h2>
              <div className="button-row">
                <button
                  className="outline"
                  disabled={busy}
                  onClick={() =>
                    void run(async (signal) => {
                      const values = await request<Dialog[]>(
                        "/telegram/dialogs",
                        "GET",
                        undefined,
                        signal,
                      );
                      if (!signal.aborted) {
                        setDialogs(values);
                        setSelected(null);
                        setMessages([]);
                      }
                    })
                  }
                >
                  Загрузить диалоги
                </button>
                <button
                  className="outline"
                  disabled={busy}
                  onClick={() =>
                    void run(async (signal) => {
                      const result = await request<{
                        added: number;
                        skipped: number;
                      }>(
                        "/telegram/import-contacts",
                        "POST",
                        undefined,
                        signal,
                      );
                      if (!signal.aborted)
                        setNotice(
                          "Добавлено контактов: " +
                            result.added +
                            "; пропущено: " +
                            result.skipped,
                        );
                    })
                  }
                >
                  Импортировать контакты Telegram
                </button>
              </div>
              <div className="mail-items">
                {dialogs.map((item) => (
                  <button
                    key={item.ticket}
                    className={
                      "mail-item" +
                      (selected?.ticket === item.ticket ? " selected" : "")
                    }
                    disabled={busy}
                    onClick={() =>
                      void run((signal) => loadMessages(item, 0, signal))
                    }
                  >
                    <strong>{item.title}</strong>
                    <small>Непрочитанных: {item.unread}</small>
                  </button>
                ))}
              </div>
            </section>
            <section className="card" aria-label="Переписка Telegram">
              <h2>{selected?.title || "Выберите диалог"}</h2>
              {messages.map((item) => (
                <article className="mail-item" key={item.id}>
                  <small>
                    {item.outgoing ? "Вы" : "Собеседник"} ·{" "}
                    {new Date(item.date).toLocaleString("ru-RU")}
                  </small>
                  <div className="note-content">{item.text}</div>
                  {item.media && (
                    <small>Есть медиа: откройте его в Telegram</small>
                  )}
                </article>
              ))}
              {selected && (
                <div className="button-row">
                  <button
                    className="outline"
                    disabled={busy}
                    onClick={() =>
                      void run((signal) => loadMessages(selected, 0, signal))
                    }
                  >
                    Обновить переписку
                  </button>
                  {before > 0 && (
                    <button
                      className="outline"
                      disabled={busy}
                      onClick={() =>
                        void run((signal) =>
                          loadMessages(selected, before, signal),
                        )
                      }
                    >
                      Предыдущие сообщения
                    </button>
                  )}
                </div>
              )}
              {selected && (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void run(async (signal) => {
                      const value = await request<Preview>(
                        "/telegram/preview",
                        "POST",
                        { dialog: selected.ticket, text },
                        signal,
                      );
                      if (!signal.aborted) {
                        setPreview(value);
                        setConfirmed(false);
                      }
                    });
                  }}
                >
                  <label>
                    Сообщение Telegram
                    <textarea
                      value={text}
                      maxLength={4000}
                      disabled={busy}
                      onChange={(event) => setText(event.target.value)}
                    />
                  </label>
                  <button className="outline" disabled={busy || !text.trim()}>
                    Проверить сообщение Telegram
                  </button>
                </form>
              )}
            </section>
          </div>
          <section className="card">
            <h2>Исходящая очередь Telegram</h2>
            <button
              className="outline"
              disabled={busy}
              onClick={() => void run(refreshOutbox)}
            >
              Обновить очередь Telegram
            </button>
            {outbox.map((item) => (
              <article className="mail-item" key={item.id}>
                <strong>{item.title}</strong>
                <small>
                  {new Date(item.created).toLocaleString("ru-RU")} ·{" "}
                  {item.state === "sent"
                    ? "Telegram подтвердил сообщение №" + item.message_id
                    : item.state === "failed"
                      ? "Telegram отклонил сообщение"
                      : "Результат пока неизвестен"}
                </small>
                <div className="note-content">{item.text}</div>
                {item.state !== "sent" && (
                  <button
                    className="outline"
                    disabled={busy}
                    onClick={() => {
                      setPreview({
                        ticket: item.id,
                        recipient: item.title,
                        text: item.text,
                        retry: true,
                      });
                      setConfirmed(false);
                    }}
                  >
                    Проверить повтор той же отправки
                  </button>
                )}
              </article>
            ))}
          </section>
        </>
      )}
      {preview && visible && (
        <section
          className="card mail-send-review"
          aria-label="Проверка сообщения Telegram"
        >
          <h2>
            {preview.retry
              ? "Повторная проверка отправки"
              : "Проверьте сообщение Telegram"}
          </h2>
          <p>Получатель: {preview.recipient}</p>
          <pre className="mail-body">{preview.text}</pre>
          {preview.retry && (
            <p>
              Будет проверена та же отправка. Повтор использует прежний
              идентификатор сообщения.
            </p>
          )}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            Получатель и текст Telegram проверены
          </label>
          <div className="button-row">
            <button
              className="primary"
              disabled={!confirmed || busy}
              onClick={() =>
                void run(async () => {
                  const value = preview;
                  setPreview(null);
                  setSending(true);
                  try {
                    const result = await request<{
                      state: string;
                      message_id: number;
                    }>(
                      value.retry
                        ? "/telegram/outbox/" + value.ticket + "/retry"
                        : "/telegram/send",
                      "POST",
                      { ticket: value.ticket, confirmed: true },
                    );
                    if (mounted.current) {
                      setNotice(
                        result.state === "sent"
                          ? "Telegram подтвердил сообщение №" +
                              result.message_id
                          : "Результат смотрите в исходящей очереди",
                      );
                      if (result.state === "sent") setText("");
                      await refreshOutbox();
                      if (selected) await loadMessages(selected);
                    }
                  } finally {
                    setSending(false);
                  }
                })
              }
            >
              {preview.retry
                ? "Подтвердить повторную проверку"
                : "Подтвердить отправку Telegram"}
            </button>
            <button
              className="outline"
              disabled={busy}
              onClick={() => setPreview(null)}
            >
              Отменить сообщение
            </button>
          </div>
        </section>
      )}
      {busy && (
        <p role="status">
          {sending
            ? "Отправляю сообщение и проверяю Telegram…"
            : "Обрабатываю Telegram…"}
        </p>
      )}
    </section>
  );
}
