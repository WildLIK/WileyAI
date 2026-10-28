import { useEffect, useMemo, useRef, useState } from "react";
import { scopedRequest, errorText } from "./api";

type Preview = {
  ticket: string;
  sender: string;
  to_addresses: string[];
  cc_addresses: string[];
  bcc_addresses: string[];
  subject: string;
  body: string;
  attachments?: { name: string; size: number; sha256: string }[];
};
type Delivery = {
  id: string;
  state: "sent" | "unknown" | "failed";
  google_id: string;
  revision: string;
};

export function MailSend({
  conversationId,
  draft,
  dirty,
  enabled,
  bound,
  visible,
  busy,
  run,
  onSending,
}: {
  conversationId: string;
  draft: { id: string; updated: string };
  dirty: boolean;
  enabled: boolean;
  bound: boolean;
  visible: boolean;
  busy: boolean;
  run: (action: (signal: AbortSignal) => Promise<void>) => Promise<void>;
  onSending: (sending: boolean) => void;
}) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [delivery, setDelivery] = useState<Delivery | null>(null);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const deliveryVersion = useRef(0);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (dirty || !visible) {
      setPreview(null);
      setConfirmed(false);
    }
  }, [dirty, visible]);
  useEffect(() => {
    if (!bound || !visible) return;
    const controller = new AbortController();
    const revision = ++deliveryVersion.current;
    void request<Delivery | null>(
      "/mail/drafts/" + draft.id + "/delivery",
      "GET",
      undefined,
      controller.signal,
    )
      .then((result) => {
        if (!controller.signal.aborted && revision === deliveryVersion.current)
          setDelivery(result);
      })
      .catch((err) => {
        if (!controller.signal.aborted && revision === deliveryVersion.current)
          setError(errorText(err));
      });
    return () => controller.abort();
  }, [bound, visible, draft.id, request]);
  return (
    <section className="mail-send" aria-label="Отправка через Gmail">
      <h3>Отправка через Gmail</h3>
      <p className="help">
        Сохраните черновик и проверьте адресатов и текст в отдельном
        предпросмотре. После подтверждения письмо отправляется с вашего аккаунта
        Gmail.
      </p>
      {!enabled && (
        <p>
          В блоке подключения Gmail выше нажмите «Разрешить отправку через
          Google» и предоставьте дополнительное разрешение. JSON повторно
          загружать не нужно.
        </p>
      )}
      {!bound && (
        <p>Выберите Gmail для этого пространства в блоке подключения выше.</p>
      )}
      {dirty && <p>Перед отправкой сохраните изменения черновика.</p>}
      {error && <p role="alert">{error}</p>}
      {delivery && (
        <div role="status">
          {delivery.state === "sent"
            ? "Google подтвердил письмо в «Отправленных». ID: " +
              delivery.google_id
            : delivery.state === "failed"
              ? "Google отклонил отправку. Проверьте доступ и адресатов, затем откройте новый предпросмотр."
              : "Результат отправки пока неизвестен. Повтор заблокирован, чтобы не отправить письмо дважды. Проверьте результат в Gmail."}
        </div>
      )}
      {delivery?.state === "unknown" && (
        <button
          className="outline"
          disabled={busy}
          onClick={() =>
            void run(async (signal) => {
              ++deliveryVersion.current;
              const result = await request<Delivery>(
                "/mail/drafts/" + draft.id + "/check-delivery",
                "POST",
                undefined,
                signal,
              );
              if (mounted.current && !signal.aborted) setDelivery(result);
            })
          }
        >
          Проверить результат отправки
        </button>
      )}
      <button
        className="outline"
        disabled={
          busy ||
          dirty ||
          !enabled ||
          !bound ||
          (!!delivery && delivery.state !== "failed")
        }
        onClick={() =>
          void run(async (signal) => {
            const result = await request<Preview>(
              "/mail/drafts/" + draft.id + "/send-preview",
              "POST",
              { expected_updated: draft.updated },
              signal,
            );
            if (mounted.current && !signal.aborted) {
              setPreview(result);
              setConfirmed(false);
            }
          })
        }
      >
        Проверить перед отправкой
      </button>
      {preview && !dirty && (
        <section
          className="mail-send-review"
          aria-label="Проверка письма перед отправкой"
        >
          <h3>Проверьте письмо</h3>
          <p>От: {preview.sender}</p>
          <p>Кому: {preview.to_addresses.join(", ") || "—"}</p>
          <p>Копия: {preview.cc_addresses.join(", ") || "—"}</p>
          <p>Скрытая копия: {preview.bcc_addresses.join(", ") || "—"}</p>
          <p>Тема: {preview.subject || "Без темы"}</p>
          <div className="mail-body">
            {preview.body || "Пустой текст письма"}
          </div>
          {!!preview.attachments?.length && (
            <div>
              <strong>Вложения ({preview.attachments.length})</strong>
              {preview.attachments.map((file, index) => (
                <p key={index}>
                  {file.name} · {Math.ceil(file.size / 1024)} КБ
                  <small> · SHA256 {file.sha256}</small>
                </p>
              ))}
            </div>
          )}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            Адресаты и текст проверены, подтверждаю отправку
          </label>
          <div className="button-row">
            <button
              className="primary"
              disabled={busy || !confirmed || !visible}
              onClick={() =>
                void run(async () => {
                  ++deliveryVersion.current;
                  setPreview(null);
                  onSending(true);
                  try {
                    // Once confirmed, aborting a fetch cannot recall an email.
                    const result = await request<Delivery>(
                      "/mail/send",
                      "POST",
                      { ticket: preview.ticket, confirmed: true },
                    );
                    if (mounted.current) setDelivery(result);
                  } finally {
                    onSending(false);
                  }
                })
              }
            >
              Подтвердить и отправить письмо
            </button>
            <button
              className="outline"
              disabled={busy}
              onClick={() => setPreview(null)}
            >
              Отменить отправку
            </button>
          </div>
        </section>
      )}
    </section>
  );
}
