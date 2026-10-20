import { useEffect, useMemo, useState } from "react";
import { scopedRequest } from "./api";
type Preview = {
  ticket: string;
  account: string;
  remote_changed: boolean;
  remote_text: string;
  to_addresses: string[];
  cc_addresses: string[];
  bcc_addresses: string[];
  subject: string;
  body: string;
  attachments: { name: string; size: number }[];
};
type Link = { state: string; remote_id?: string; message?: string };
export function MailRemote({
  conversationId,
  draft,
  enabled,
  bound,
  visible,
  dirty,
  busy,
  run,
  onWriting,
}: {
  conversationId: string;
  draft: { id: string; updated: string };
  enabled: boolean;
  bound: boolean;
  visible: boolean;
  dirty: boolean;
  busy: boolean;
  run: (action: (signal: AbortSignal) => Promise<void>) => Promise<void>;
  onWriting: (value: boolean) => void;
}) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [preview, setPreview] = useState<Preview | null>(null),
    [link, setLink] = useState<Link | null>(null),
    [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (dirty || !visible) {
      setPreview(null);
      setConfirmed(false);
    }
  }, [dirty, visible]);
  useEffect(() => {
    if (!bound || !visible) return;
    const controller = new AbortController();
    void request<Link | null>(
      "/mail/drafts/" + draft.id + "/remote",
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setLink(value);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [request, draft.id, bound, visible]);
  return (
    <section className="mail-send" aria-label="Черновик Gmail">
      <h3>Черновик Gmail</h3>
      <p className="help">
        Сохранение в Gmail — отдельное действие после просмотра. Письмо при этом
        не отправляется.
      </p>
      {!enabled && (
        <p>
          В подключении Gmail нажмите «Разрешить черновики через Google».
          Используется уже сохранённый JSON.
        </p>
      )}
      {link && (
        <p role="status">
          {link.state === "ready"
            ? "Черновик Gmail проверен: " + link.remote_id
            : link.state === "sent"
              ? "Черновик отправлен"
              : "Сохранение пока не подтверждено. Проверьте результат перед повтором."}
        </p>
      )}
      <div className="button-row">
        <button
          className="outline"
          disabled={
            busy || dirty || !enabled || !bound || link?.state === "unknown"
          }
          onClick={() =>
            void run(async (signal) => {
              const value = await request<Preview>(
                "/mail/drafts/" + draft.id + "/remote-preview",
                "POST",
                { expected_updated: draft.updated },
                signal,
              );
              if (!signal.aborted) {
                setPreview(value);
                setConfirmed(false);
              }
            })
          }
        >
          Сравнить и сохранить в Gmail
        </button>
        {link?.state === "unknown" && (
          <button
            className="outline"
            disabled={busy}
            onClick={() =>
              void run(async (signal) => {
                const value = await request<Link>(
                  "/mail/drafts/" + draft.id + "/remote-check",
                  "POST",
                  undefined,
                  signal,
                );
                if (!signal.aborted) setLink(value);
              })
            }
          >
            Проверить черновик Gmail
          </button>
        )}
      </div>
      {preview && !dirty && (
        <section className="mail-send-review" aria-label="Сравнение черновиков">
          <h3>Сохранить показанное письмо в Gmail</h3>
          <p>Аккаунт: {preview.account}</p>
          <p>Кому: {preview.to_addresses.join(", ") || "—"}</p>
          <p>Копия: {preview.cc_addresses.join(", ") || "—"}</p>
          <p>Скрытая копия: {preview.bcc_addresses.join(", ") || "—"}</p>
          <p>Тема: {preview.subject}</p>
          <div className="mail-body">{preview.body}</div>
          {preview.attachments.map((item, index) => (
            <p key={index}>
              Вложение: {item.name} · {Math.ceil(item.size / 1024)} КБ
            </p>
          ))}
          {preview.remote_changed && (
            <div>
              <strong>
                Версия Gmail менялась. При подтверждении она будет заменена
                показанной локальной копией.
              </strong>
              <pre className="mail-body">{preview.remote_text}</pre>
            </div>
          )}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              disabled={busy}
            />
            Подтверждаю сохранение этой версии в Gmail
          </label>
          <div className="button-row">
            <button
              className="primary"
              disabled={!confirmed || busy || !visible}
              onClick={() =>
                void run(async () => {
                  setPreview(null);
                  onWriting(true);
                  try {
                    setLink(
                      await request<Link>("/mail/remote-save", "POST", {
                        ticket: preview.ticket,
                        confirmed: true,
                      }),
                    );
                  } finally {
                    onWriting(false);
                  }
                })
              }
            >
              Подтвердить сохранение в Gmail
            </button>
            <button
              className="outline"
              disabled={busy}
              onClick={() => setPreview(null)}
            >
              Отменить сохранение
            </button>
          </div>
        </section>
      )}
    </section>
  );
}
