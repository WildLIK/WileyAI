import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { scopedRequest, errorText } from "./api";
import { poll } from "./polling";
import { ProcessStatus } from "./ProcessStatus";
import { MailSend } from "./MailSend";
import { MailRemote } from "./MailRemote";
type Attachment = { name: string; type: string; data: string };

type Draft = {
  id: string;
  to_addresses: string[];
  cc_addresses: string[];
  bcc_addresses: string[];
  subject: string;
  body: string;
  attachments?: Attachment[];
  preview?: string;
  updated: string;
  source_account: string | null;
  source_message_id: string | null;
};
type Summary = {
  ticket: string;
  subject: string;
  sender: string;
  date: string;
  unread: boolean;
  snippet: string;
};
type Letter = Summary & {
  text: string;
  reply_to: string;
  reply_addresses: string[];
  truncated: boolean;
  from_html: boolean;
  notes: string[];
  attachments: { name: string; type: string; ticket?: string }[];
  account: string;
};
type Inbox = {
  messages: Summary[];
  next_cursor: string | null;
  account: string;
  checked_at: string;
};
type Status = {
  configured: boolean;
  connected: boolean;
  send_enabled: boolean;
  drafts_enabled: boolean;
  pending: boolean;
  error: string;
  binding: { id: string; account: string } | null;
  model: string;
  model_location: "local" | "cloud";
};
type Editor = {
  attachments: Attachment[];
  to: string;
  cc: string;
  bcc: string;
  subject: string;
  body: string;
};
type Proposal = {
  text: string;
  expected_updated: string;
  source_partial: boolean;
  source_chars: number;
};
const blank = (): Editor => ({
  attachments: [],
  to: "",
  cc: "",
  bcc: "",
  subject: "",
  body: "",
});
const editorFor = (draft: Draft): Editor => ({
  attachments: draft.attachments || [],
  to: draft.to_addresses.join(", "),
  cc: draft.cc_addresses.join(", "),
  bcc: draft.bcc_addresses.join(", "),
  subject: draft.subject,
  body: draft.body,
});
const addresses = (value: string) =>
  value
    .split(/[,;]/)
    .map((item) => item.trim())
    .filter(Boolean);

export const MailPanel = memo(function MailPanel({
  conversationId,
  scopeName,
  visible = true,
}: {
  conversationId: string;
  scopeName: string;
  visible?: boolean;
}) {
  const [visited, setVisited] = useState(false);
  useEffect(() => {
    if (visible) setVisited(true);
  }, [visible]);
  if (!visible && !visited) return null;
  return (
    <div style={{ display: visible ? "contents" : "none" }}>
      <MailContent
        conversationId={conversationId}
        scopeName={scopeName}
        visible={visible}
      />
    </div>
  );
});

function MailContent({
  conversationId,
  scopeName,
  visible,
}: {
  conversationId: string;
  scopeName: string;
  visible: boolean;
}) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [status, setStatus] = useState<Status | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selected, setSelected] = useState<Draft | null>(null);
  const [editor, setEditor] = useState<Editor>(blank);
  const [folder, setFolder] = useState("inbox");
  const [query, setQuery] = useState("");
  const [loadedQuery, setLoadedQuery] = useState<{
    query: string;
    folder: string;
  } | null>(null);
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [letter, setLetter] = useState<Letter | null>(null);
  const [selectedMessage, setSelectedMessage] = useState("");
  const [instructions, setInstructions] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [contacts, setContacts] = useState<
    { id: string; name: string; email: string }[]
  >([]);
  useEffect(() => {
    if (!visible) return;
    let live = true;
    void request<{ id: string; name: string; email: string }[]>("/contacts")
      .then((values) => {
        if (live) setContacts(values.filter((item) => item.email));
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [visible, request]);
  const mounted = useRef(true);
  const active = useRef<AbortController | null>(null);
  const channel = useRef<BroadcastChannel | null>(null);
  const previousStatus = useRef<string | null>(null);
  const statusRequest = useRef(0);
  const dirty = useMemo(
    () =>
      JSON.stringify({ ...editor, attachments: undefined }) !==
        JSON.stringify({
          ...(selected ? editorFor(selected) : blank()),
          attachments: undefined,
        }) ||
      editor.attachments.length !== (selected?.attachments?.length || 0) ||
      editor.attachments.some((value, index) => {
        const previous = selected?.attachments?.[index];
        return (
          !previous ||
          value.name !== previous.name ||
          value.type !== previous.type ||
          value.data !== previous.data
        );
      }),
    [editor, selected],
  );
  const refreshStatus = useCallback(
    async (signal?: AbortSignal) => {
      const revision = ++statusRequest.current;
      const value = await request<Status>(
        "/mail/status",
        "GET",
        undefined,
        signal,
      );
      if (
        mounted.current &&
        !signal?.aborted &&
        revision === statusRequest.current
      ) {
        const key = JSON.stringify([
          value.configured,
          value.connected,
          value.pending,
          value.binding,
        ]);
        if (previousStatus.current !== null && previousStatus.current !== key)
          channel.current?.postMessage({ type: "account-changed" });
        previousStatus.current = key;
        setStatus(value);
      }
    },
    [request],
  );
  const refreshDrafts = async (signal?: AbortSignal) => {
    const value = await request<Draft[]>(
      "/mail/drafts",
      "GET",
      undefined,
      signal,
    );
    if (mounted.current) setDrafts(value);
  };
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void Promise.allSettled([
      refreshStatus(controller.signal),
      refreshDrafts(controller.signal),
    ]).then((results) => {
      for (const result of results)
        if (
          result.status === "rejected" &&
          mounted.current &&
          !controller.signal.aborted
        )
          setError(errorText(result.reason));
    });
    const bus = new BroadcastChannel("wiley-mail");
    channel.current = bus;
    bus.onmessage = (event) => {
      if (event.data?.type === "account-changed") {
        void refreshStatus(controller.signal).catch((err) => {
          if (mounted.current && !controller.signal.aborted)
            setError(errorText(err));
        });
      }
      void refreshDrafts(controller.signal).catch((err) => {
        if (mounted.current && !controller.signal.aborted)
          setError(errorText(err));
      });
    };
    const returned = () => {
      if (document.visibilityState === "hidden") return;
      void refreshStatus(controller.signal).catch((err) => {
        if (mounted.current && !controller.signal.aborted)
          setError(errorText(err));
      });
    };
    window.addEventListener("focus", returned);
    document.addEventListener("visibilitychange", returned);
    return () => {
      mounted.current = false;
      controller.abort();
      active.current?.abort();
      bus.close();
      window.removeEventListener("focus", returned);
      document.removeEventListener("visibilitychange", returned);
    };
  }, [request, refreshStatus]);
  useEffect(() => {
    if (!status?.pending) return;
    return poll(
      (signal) =>
        refreshStatus(signal).catch((err) => {
          if (!signal.aborted) setError(errorText(err));
        }),
      2000,
      { immediate: false },
    );
  }, [status?.pending, refreshStatus]);
  useEffect(() => {
    setInbox(null);
    setLetter(null);
    setLoadedQuery(null);
    setSelectedMessage("");
  }, [status?.binding?.id]);
  useEffect(() => {
    if (!visible && !sending) active.current?.abort();
  }, [visible, sending]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
    };
  }, [dirty]);
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
      if (mounted.current) {
        setBusy(false);
        setGenerating(false);
      }
    }
  }
  const changed = () => {
    channel.current?.postMessage({ type: "draft-changed" });
  };
  function openDraft(draft: Draft | null) {
    setSelected(draft);
    setEditor(draft ? editorFor(draft) : blank());
    setProposal(null);
    setInstructions("");
  }
  const canDiscard = () =>
    !dirty ||
    window.confirm(
      "В черновике есть несохранённые изменения. Продолжить без их сохранения?",
    );
  async function save(signal: AbortSignal) {
    const route = selected
      ? "/mail/drafts/" +
        selected.id +
        "?expected_updated=" +
        encodeURIComponent(selected.updated)
      : "/mail/drafts";
    const draft = await request<Draft>(
      route,
      selected ? "PUT" : "POST",
      {
        to_addresses: addresses(editor.to),
        cc_addresses: addresses(editor.cc),
        bcc_addresses: addresses(editor.bcc),
        subject: editor.subject,
        body: editor.body,
        attachments: editor.attachments,
      },
      signal,
    );
    if (!mounted.current || signal.aborted) return;
    openDraft(draft);
    changed();
    await refreshDrafts(signal);
    setNotice("Черновик сохранён в WileyAI");
  }
  async function loadInbox(signal: AbortSignal, cursor?: string) {
    const search = cursor && loadedQuery ? loadedQuery : { query, folder };
    setInbox(null);
    setLetter(null);
    setSelectedMessage("");
    const result = await request<Inbox>(
      "/mail/inbox",
      "POST",
      { ...search, cursor: cursor || null },
      signal,
    );
    if (mounted.current && !signal.aborted) {
      setInbox(result);
      setLoadedQuery(search);
      setLetter(null);
    }
  }
  return (
    <section className="page scroll-page mail-page">
      <div className="page-heading">
        <div>
          <h1>Почта и черновики</h1>
          <p>
            {scopeName
              .replace("Память проекта", "Почта проекта")
              .replace("Общая память", "Общая почта")}
          </p>
          <p className="help">
            Читайте Gmail и готовьте ответы. Черновики хранятся в WileyAI; файл
            EML можно открыть в почтовом приложении для дальнейшей работы.
            Отправка через Gmail доступна после отдельного разрешения и проверки
            письма.
          </p>
        </div>
      </div>
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
      <details className="card mail-connection" open={!status?.binding}>
        <summary>
          Подключение Gmail
          {status?.binding ? " · " + status.binding.account : ""}
        </summary>
        <p>
          Для чтения нужен отдельный вход Gmail. Подключение календаря не даёт
          доступ к письмам.
        </p>
        <p role="status">
          {!status
            ? "Проверяю подключение Gmail…"
            : status.pending
              ? "Ожидаю вход в браузере…"
              : status.connected
                ? "Вход в Gmail выполнен"
                : "Gmail не подключён"}
        </p>
        {status?.configured && (
          <p className="help">
            JSON OAuth-клиента сохранён. Повторно выбирать файл не нужно.
          </p>
        )}
        {status?.connected && !status.binding && (
          <p className="help">
            Чтобы читать входящие, нажмите «Использовать Gmail в этом
            пространстве». Затем в разделе «Письма Gmail» нажмите «Загрузить
            письма».
          </p>
        )}
        {!status?.connected && (
          <details>
            <summary>Настроить доступ Gmail</summary>
            <p>
              В Google Cloud включите Gmail API и создайте OAuth client ID типа
              Desktop app. Скачайте JSON клиента, добавьте свой адрес в Test
              users, если приложение в режиме Testing, и загрузите файл здесь.
              Запрашивается только чтение писем.
            </p>
            <label>
              JSON клиента Gmail Desktop app
              <input
                type="file"
                accept=".json,application/json"
                disabled={busy || status?.pending}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (!file) return;
                  void run(async (signal) => {
                    if (file.size > 16384)
                      throw new Error("JSON клиента превышает 16 КБ");
                    await request(
                      "/mail/gmail/client",
                      "PUT",
                      { document: await file.text() },
                      signal,
                    );
                    await refreshStatus(signal);
                    if (mounted.current && !signal.aborted)
                      setNotice(
                        "JSON клиента Gmail сохранён. Теперь нажмите «Войти в Gmail через Google»",
                      );
                  });
                }}
              />
            </label>
          </details>
        )}
        <div className="button-row">
          <button
            className="subtle"
            disabled={busy}
            onClick={() => void run(refreshStatus)}
          >
            Обновить статус Gmail
          </button>
          {!status?.connected && !status?.pending && (
            <button
              className="outline"
              disabled={busy || !status?.configured}
              onClick={() =>
                void run(async (signal) => {
                  await window.wiley.gmailLogin();
                  await refreshStatus(signal);
                })
              }
            >
              Войти в Gmail через Google
            </button>
          )}
          {status?.pending && (
            <button
              className="outline"
              disabled={busy}
              onClick={() =>
                void run(async (signal) => {
                  await request(
                    "/mail/gmail/cancel",
                    "POST",
                    undefined,
                    signal,
                  );
                  await refreshStatus(signal);
                })
              }
            >
              Отменить вход Gmail
            </button>
          )}
          {status?.connected && (
            <>
              {!status.drafts_enabled && (
                <>
                  <button
                    className="outline"
                    disabled={busy || status.pending}
                    onClick={() =>
                      void run(async (signal) => {
                        await window.wiley.gmailDraftsLogin();
                        await refreshStatus(signal);
                      })
                    }
                  >
                    Разрешить черновики через Google
                  </button>
                  <p className="help">
                    Разрешение Google для черновиков также включает отправку
                    писем. В WileyAI отправка требует отдельного предпросмотра и
                    подтверждения.
                  </p>
                </>
              )}
              {!status.send_enabled && (
                <button
                  className="outline"
                  disabled={busy || status.pending}
                  onClick={() =>
                    void run(async (signal) => {
                      await window.wiley.gmailSendLogin();
                      await refreshStatus(signal);
                    })
                  }
                >
                  Разрешить отправку через Google
                </button>
              )}
              <button
                className="outline"
                disabled={busy}
                onClick={() =>
                  void run(async (signal) => {
                    await request(
                      "/mail/gmail/binding",
                      "PUT",
                      undefined,
                      signal,
                    );
                    await refreshStatus(signal);
                    if (mounted.current && !signal.aborted)
                      setNotice(
                        "Аккаунт выбран. Нажмите «Загрузить письма», чтобы открыть входящие",
                      );
                  })
                }
              >
                Использовать Gmail в этом пространстве
              </button>
              <button
                className="subtle"
                disabled={busy}
                onClick={() =>
                  void run(async (signal) => {
                    await request(
                      "/mail/gmail/disconnect",
                      "POST",
                      undefined,
                      signal,
                    );
                    setInbox(null);
                    setLetter(null);
                    await refreshStatus(signal);
                  })
                }
              >
                Отключить вход Gmail
              </button>
            </>
          )}
          {status?.binding && (
            <button
              className="subtle"
              disabled={busy}
              onClick={() =>
                void run(async (signal) => {
                  await request(
                    "/mail/gmail/binding",
                    "DELETE",
                    undefined,
                    signal,
                  );
                  setInbox(null);
                  setLetter(null);
                  await refreshStatus(signal);
                })
              }
            >
              Убрать почту из этого пространства
            </button>
          )}
        </div>
        {status?.error && <p role="alert">{status.error}</p>}
      </details>
      {status?.binding ? (
        <div className="mail-grid">
          <section className="card">
            <h2>Письма Gmail</h2>
            <p className="hint">
              В чате или голосом: «Прочитай последнее письмо из Gmail» или
              «Прочитай последнее непрочитанное письмо».
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void run((signal) => loadInbox(signal));
              }}
            >
              <fieldset disabled={busy}>
                <label>
                  Папка Gmail
                  <select
                    aria-label="Папка Gmail"
                    value={folder}
                    onChange={(event) => setFolder(event.target.value)}
                  >
                    <option value="inbox">Входящие</option>
                    <option value="unread">Непрочитанные во входящих</option>
                    <option value="sent">Отправленные</option>
                  </select>
                </label>
                <label>
                  Поиск Gmail
                  <input
                    maxLength={500}
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Текст или from:name@example.com"
                  />
                </label>
                <button className="outline">Загрузить письма</button>
              </fieldset>
            </form>
            <p className="help">
              Загружается до 20 писем за страницу. Просмотр не меняет отметку
              прочтения.
            </p>
            {inbox && (
              <>
                <small>
                  Проверено:{" "}
                  {new Date(inbox.checked_at).toLocaleString("ru-RU")} ·{" "}
                  {inbox.account}
                </small>
                {!inbox.messages.length && <p>На этой странице писем нет.</p>}
                <div className="mail-items">
                  {inbox.messages.map((item) => (
                    <button
                      className={
                        "mail-item" +
                        (selectedMessage === item.ticket ? " selected" : "")
                      }
                      aria-pressed={selectedMessage === item.ticket}
                      key={item.ticket}
                      disabled={busy}
                      onClick={() =>
                        void run(async (signal) => {
                          const result = await request<Letter>(
                            "/mail/messages/" + item.ticket,
                            "GET",
                            undefined,
                            signal,
                          );
                          if (mounted.current && !signal.aborted) {
                            setLetter(result);
                            setSelectedMessage(item.ticket);
                          }
                        })
                      }
                    >
                      <strong>
                        {item.unread ? "● " : ""}
                        {item.subject}
                      </strong>
                      <small>{item.sender}</small>
                      <small>{item.date}</small>
                      <span className="mail-snippet">{item.snippet}</span>
                    </button>
                  ))}
                </div>
                {inbox.next_cursor && (
                  <button
                    className="outline"
                    disabled={busy}
                    onClick={() =>
                      void run((signal) =>
                        loadInbox(signal, inbox.next_cursor!),
                      )
                    }
                  >
                    Следующая страница писем
                  </button>
                )}
              </>
            )}
          </section>
          <section className="card mail-reader" aria-label="Просмотр письма">
            <h2>{letter?.subject || "Выберите письмо"}</h2>
            {letter && (
              <>
                <p>От: {letter.sender}</p>
                {letter.reply_to && <p>Адрес ответа: {letter.reply_to}</p>}
                <p>{letter.date}</p>
                {letter.from_html && (
                  <p className="help">
                    Текст извлечён из HTML. Изображения и внешние ресурсы не
                    загружаются.
                  </p>
                )}
                {letter.notes.map((note) => (
                  <p className="help" key={note}>
                    {note}
                  </p>
                ))}
                <div className="mail-body">
                  {letter.text ||
                    "В письме нет доступного текстового содержимого."}
                </div>
                {!!letter.attachments.length && (
                  <details>
                    <summary>Вложения ({letter.attachments.length})</summary>
                    {letter.attachments.map((attachment, index) => (
                      <p key={index}>
                        {attachment.name} · {attachment.type}
                        {attachment.ticket && (
                          <button
                            className="outline"
                            disabled={busy}
                            onClick={() =>
                              void run(async () => {
                                const result =
                                  await window.wiley.exportAttachment({
                                    ticket: attachment.ticket!,
                                    conversationId,
                                    name: attachment.name,
                                  });
                                if (result && mounted.current)
                                  setNotice(
                                    "Вложение сохранено: " + result.path,
                                  );
                              })
                            }
                          >
                            Сохранить вложение
                          </button>
                        )}
                      </p>
                    ))}
                    <p className="help">
                      Вложение сохраняется по вашему нажатию, до 5 МБ за файл.
                    </p>
                  </details>
                )}
                <button
                  className="outline"
                  disabled={busy || !letter.reply_addresses.length}
                  onClick={() => {
                    if (!canDiscard()) return;
                    void run(async (signal) => {
                      const draft = await request<Draft>(
                        "/mail/reply",
                        "POST",
                        { ticket: letter.ticket },
                        signal,
                      );
                      if (!mounted.current || signal.aborted) return;
                      openDraft(draft);
                      changed();
                      await refreshDrafts(signal);
                      setNotice(
                        "Создан местный черновик ответа. Проверьте получателя и напишите текст",
                      );
                    });
                  }}
                >
                  Подготовить ответ на это письмо
                </button>
              </>
            )}
          </section>
        </div>
      ) : (
        <section className="card mail-inbox-placeholder">
          <h2>Письма Gmail</h2>
          <p>
            {!status
              ? "Проверяю доступ к входящим…"
              : status.connected
                ? "Вход выполнен. Выберите «Использовать Gmail в этом пространстве» в блоке подключения выше."
                : "Входящие, непрочитанные и отправленные письма будут доступны после подключения Gmail."}
          </p>
        </section>
      )}
      <div className="mail-grid">
        <section className="card">
          <h2>Локальные черновики ({drafts.length})</h2>
          <button
            className="outline"
            disabled={busy}
            onClick={() => {
              if (canDiscard()) openDraft(null);
            }}
          >
            Новый черновик
          </button>
          <button
            className="subtle"
            disabled={busy}
            onClick={() => void run(refreshDrafts)}
          >
            Обновить черновики
          </button>
          <div className="mail-items">
            {drafts.map((draft) => (
              <button
                key={draft.id}
                disabled={busy}
                className={
                  "mail-item" + (selected?.id === draft.id ? " selected" : "")
                }
                onClick={() => {
                  if (!canDiscard()) return;
                  void run(async (signal) => {
                    const value = await request<Draft>(
                      "/mail/drafts/" + draft.id,
                      "GET",
                      undefined,
                      signal,
                    );
                    if (mounted.current && !signal.aborted) openDraft(value);
                  });
                }}
              >
                <strong>{draft.subject || "Без темы"}</strong>
                <small>
                  {draft.to_addresses.join(", ") || "Получатель пока не указан"}
                </small>
                <span>{draft.preview}</span>
              </button>
            ))}
          </div>
        </section>
        <section className="card mail-editor">
          <h2>{selected ? "Редактор черновика" : "Новое письмо"}</h2>
          <p className="help">
            {dirty
              ? "Есть несохранённые изменения. Переход между вкладками сохраняет редактор; перед закрытием программы нажмите «Сохранить черновик»."
              : selected
                ? "Черновик сохранён локально"
                : "Черновик можно создать без подключения Gmail"}
          </p>
          {selected?.source_account && (
            <p className="help">Ответ на письмо из {selected.source_account}</p>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void run(save);
            }}
          >
            <fieldset disabled={busy}>
              {!!contacts.length && (
                <label>
                  Добавить получателя из контактов
                  <select
                    value=""
                    onChange={(event) => {
                      const contact = contacts.find(
                        (item) => item.id === event.target.value,
                      );
                      if (contact)
                        setEditor({
                          ...editor,
                          to: [editor.to, contact.email]
                            .filter(Boolean)
                            .join(", "),
                        });
                    }}
                  >
                    <option value="">Выберите контакт</option>
                    {contacts.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} · {item.email}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {(
                [
                  ["to", "Кому"],
                  ["cc", "Копия"],
                  ["bcc", "Скрытая копия"],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    value={editor[key]}
                    onChange={(event) =>
                      setEditor({ ...editor, [key]: event.target.value })
                    }
                    placeholder="name@example.com, other@example.com"
                    maxLength={6000}
                  />
                </label>
              ))}
              <label>
                Тема письма
                <input
                  maxLength={300}
                  value={editor.subject}
                  onChange={(event) =>
                    setEditor({ ...editor, subject: event.target.value })
                  }
                />
              </label>
              <label>
                Текст письма
                <textarea
                  aria-label="Текст письма"
                  rows={12}
                  maxLength={100000}
                  value={editor.body}
                  onChange={(event) =>
                    setEditor({ ...editor, body: event.target.value })
                  }
                />
              </label>
              <label>
                Добавить вложения (до 5 МБ на файл, всего 10 МБ)
                <input
                  type="file"
                  multiple
                  onChange={(event) => {
                    const files = Array.from(event.target.files || []);
                    event.target.value = "";
                    void run(async (signal) => {
                      if (
                        editor.attachments.length + files.length > 10 ||
                        files.some((file) => file.size > 5 * 1024 * 1024)
                      )
                        throw new Error(
                          "До 10 вложений, каждое не больше 5 МБ",
                        );
                      const added: Attachment[] = [];
                      for (const file of files) {
                        const data = await new Promise<string>(
                          (resolve, reject) => {
                            const reader = new FileReader();
                            reader.onerror = () =>
                              reject(new Error("Не удалось прочитать файл"));
                            reader.onload = () =>
                              resolve(String(reader.result).split(",")[1]);
                            reader.readAsDataURL(file);
                          },
                        );
                        added.push({
                          name: file.name,
                          type: file.type || "application/octet-stream",
                          data,
                        });
                      }
                      const attachments = [...editor.attachments, ...added];
                      if (
                        attachments.reduce(
                          (sum, item) => sum + item.data.length * 0.75,
                          0,
                        ) >
                        10 * 1024 * 1024
                      )
                        throw new Error("Сумма вложений превышает 10 МБ");
                      if (!signal.aborted && mounted.current)
                        setEditor({ ...editor, attachments });
                    });
                  }}
                />
              </label>
              {editor.attachments.map((item, index) => (
                <p key={index}>
                  {item.name}{" "}
                  <button
                    type="button"
                    className="subtle danger"
                    onClick={() =>
                      setEditor({
                        ...editor,
                        attachments: editor.attachments.filter(
                          (_, i) => i !== index,
                        ),
                      })
                    }
                  >
                    Убрать вложение
                  </button>
                </p>
              ))}
              <div className="button-row">
                <button className="primary">Сохранить черновик</button>
                <button
                  type="button"
                  className="outline"
                  disabled={!selected || dirty}
                  onClick={() =>
                    void run(async () => {
                      const result = await window.wiley.exportMail({
                        id: selected!.id,
                        conversationId,
                        updated: selected!.updated,
                      });
                      if (mounted.current && result)
                        setNotice("Файл черновика сохранён: " + result.path);
                    })
                  }
                >
                  Сохранить файл EML
                </button>
                {selected && (
                  <button
                    type="button"
                    className="subtle danger"
                    onClick={() => {
                      if (!canDiscard()) return;
                      void run(async (signal) => {
                        await request(
                          "/mail/drafts/" +
                            selected.id +
                            "?expected_updated=" +
                            encodeURIComponent(selected.updated),
                          "DELETE",
                          undefined,
                          signal,
                        );
                        if (!mounted.current || signal.aborted) return;
                        openDraft(null);
                        changed();
                        await refreshDrafts(signal);
                        setNotice("Местный черновик удалён");
                      });
                    }}
                  >
                    Удалить черновик
                  </button>
                )}
                {dirty && (
                  <button
                    type="button"
                    className="subtle"
                    onClick={() => {
                      if (canDiscard()) openDraft(selected);
                    }}
                  >
                    Отменить изменения
                  </button>
                )}
              </div>
            </fieldset>
          </form>
          {selected && (
            <MailRemote
              key={
                "remote" + selected.id + selected.updated + status?.binding?.id
              }
              conversationId={conversationId}
              draft={selected}
              dirty={dirty}
              enabled={!!status?.drafts_enabled}
              bound={!!status?.binding}
              visible={visible}
              busy={busy}
              run={run}
              onWriting={setSending}
            />
          )}
          {selected && (
            <MailSend
              key={selected.id + selected.updated + status?.binding?.id}
              conversationId={conversationId}
              draft={selected}
              dirty={dirty}
              enabled={!!status?.send_enabled}
              bound={!!status?.binding}
              visible={visible}
              busy={busy}
              run={run}
              onSending={setSending}
            />
          )}
          <details className="mail-assistant">
            <summary>Подготовить текст моделью</summary>
            <p className="help">
              Кнопка передаст выбранной модели текст черновика и, для ответа,
              исходное письмо. При облачном подключении данные получит внешний
              сервис. Получатели и тема остаются под вашим управлением.
            </p>
            <p className="help">
              Модель: {status?.model || "выбранная в настройках"}
              {status?.model_location === "cloud"
                ? " · внешний сервер"
                : status?.model_location === "local"
                  ? " · локальная"
                  : ""}
              . Сначала сохраните изменения черновика.
            </p>
            <label>
              Что написать в письме
              <textarea
                aria-label="Что написать в письме"
                rows={3}
                maxLength={2000}
                disabled={busy}
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
                placeholder="Поблагодари за предложение и попроси прислать подробности"
              />
            </label>
            <button
              className="outline"
              disabled={busy || !selected || dirty || !instructions.trim()}
              onClick={() =>
                void run(async (signal) => {
                  setGenerating(true);
                  setProposal(null);
                  const result = await request<Proposal>(
                    "/mail/drafts/" + selected!.id + "/suggest",
                    "POST",
                    {
                      expected_updated: selected!.updated,
                      instructions,
                      allow_cloud: status?.model_location === "cloud",
                    },
                    signal,
                  );
                  if (mounted.current && !signal.aborted) setProposal(result);
                })
              }
            >
              Составить текст письма
            </button>
            {proposal && (
              <div className="mail-proposal">
                <h3>Предложенный текст</h3>
                {proposal.source_partial && (
                  <p className="help">
                    Исходное письмо использовано частично:{" "}
                    {proposal.source_chars} символов. Проверьте, хватает ли
                    контекста.
                  </p>
                )}
                <div className="mail-body">{proposal.text}</div>
                <button
                  className="outline"
                  disabled={
                    busy ||
                    dirty ||
                    selected?.updated !== proposal.expected_updated
                  }
                  onClick={() => {
                    setEditor({ ...editor, body: proposal.text });
                    setProposal(null);
                    setNotice(
                      "Текст подставлен в редактор. Проверьте и сохраните черновик",
                    );
                  }}
                >
                  Подставить текст в черновик
                </button>
              </div>
            )}
          </details>
        </section>
      </div>
      {busy && (
        <div className="mail-progress">
          <ProcessStatus
            kind={generating ? "brain" : "search"}
            label={
              sending
                ? "Отправляю письмо и проверяю Gmail…"
                : generating
                  ? "Составляю текст письма…"
                  : "Обрабатываю почту…"
            }
            detail={
              generating
                ? "Черновик остаётся под вашим управлением"
                : "Ожидаю результат операции"
            }
          />
          <button
            className="outline"
            disabled={sending}
            onClick={() => active.current?.abort()}
          >
            Остановить
          </button>
        </div>
      )}
    </section>
  );
}
