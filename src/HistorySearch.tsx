import { useEffect, useRef, useState } from "react";
import { request, scoped } from "./api";
import { ProcessStatus } from "./ProcessStatus";

export interface HistoryHit {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  created: string;
  title: string;
  project_id: string | null;
  project_name: string | null;
  preview: string;
}
type Results = { items: HistoryHit[]; total: number; terms: string[] };

export function HistorySearch({
  chat,
  project,
  initialScope,
  onClose,
  onSelect,
  disabled,
}: {
  chat: string;
  project?: string;
  initialScope: "chat" | "space";
  onClose: () => void;
  onSelect: (hit: HistoryHit, terms: string[]) => void;
  disabled: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [scope, setScope] = useState<string>(initialScope);
  const [role, setRole] = useState("all");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<Results>({ items: [], total: 0, terms: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    element?.showModal();
    input.current?.focus();
    return () => {
      element?.close();
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => {
      setOffset(0);
      setSubmitted(query.trim());
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    if (submitted.length < 2) {
      setData({ items: [], total: 0, terms: [] });
      setLoading(false);
      return;
    }
    setLoading(true);
    void request<Results>(
      scoped(
        "/history/search?" +
          new URLSearchParams({
            q: submitted,
            scope,
            role,
            offset: String(offset),
          }),
        chat,
      ),
      "GET",
      undefined,
      controller.signal,
    )
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Не удалось найти сообщения",
          );
          setData({ items: [], total: 0, terms: [] });
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [submitted, scope, role, offset, chat]);
  const pending = loading || query.trim() !== submitted;
  return (
    <dialog
      ref={dialog}
      className="history-search-dialog"
      aria-labelledby="history-search-title"
      onKeyDown={(event) => {
        if (
          event.key === "Escape" &&
          !event.ctrlKey &&
          !event.shiftKey &&
          !event.altKey &&
          !event.metaKey
        ) {
          event.preventDefault();
          onClose();
        }
      }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header>
        <div>
          <h2 id="history-search-title">Поиск в переписке</h2>
          <p>По тексту сообщений · локально на этом ПК</p>
        </div>
        <button
          className="subtle"
          aria-label="Закрыть поиск в переписке"
          onClick={onClose}
        >
          ×
        </button>
      </header>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setOffset(0);
          setSubmitted(query.trim());
        }}
      >
        <div className="history-query">
          <input
            ref={input}
            type="search"
            aria-label="Поиск по сообщениям"
            maxLength={200}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Решение, название, контрольный код…"
          />
          <button
            className="outline"
            type="submit"
            disabled={query.trim().length < 2}
          >
            Найти
          </button>
        </div>
        <div className="history-filters">
          <label>
            Где искать
            <select
              aria-label="Область поиска переписки"
              value={scope}
              onChange={(event) => {
                setOffset(0);
                setScope(event.target.value);
              }}
            >
              <option value="chat">Текущий чат</option>
              <option value="space">
                {project ? "Проект «" + project + "»" : "Общие чаты"}
              </option>
              <option value="all">Все чаты и проекты</option>
            </select>
          </label>
          <label>
            Автор
            <select
              aria-label="Автор сообщения"
              value={role}
              onChange={(event) => {
                setOffset(0);
                setRole(event.target.value);
              }}
            >
              <option value="all">Все сообщения</option>
              <option value="user">Только мои</option>
              <option value="assistant">Только ассистент</option>
            </select>
          </label>
        </div>
      </form>
      <div className="history-results" aria-busy={pending}>
        {error && (
          <p className="device-error" role="alert">
            {error}
          </p>
        )}
        {pending ? (
          <ProcessStatus kind="search" label="Ищу сообщения…" compact />
        ) : submitted.length < 2 ? (
          <p className="help">
            Введите хотя бы два символа. Можно искать по нескольким словам, до
            12.
          </p>
        ) : !data.total ? (
          <p className="help">Совпадений не найдено.</p>
        ) : (
          <>
            <p className="help">
              Найдено: {data.total} · {offset + 1}–
              {Math.min(offset + 20, data.total)}
            </p>
            <ol>
              {data.items.map((hit) => (
                <li key={hit.id}>
                  <button
                    className="history-result"
                    disabled={disabled}
                    onClick={() => onSelect(hit, data.terms)}
                  >
                    <strong>{hit.title}</strong>
                    <small>
                      {hit.project_name || "Общие чаты"} ·{" "}
                      {hit.role === "user" ? "Вы" : "Ассистент"} ·{" "}
                      {new Date(hit.created).toLocaleString("ru-RU")}
                    </small>
                    <p>{hit.preview}</p>
                  </button>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
      {!pending && data.total > 20 && (
        <footer>
          <button
            className="outline"
            disabled={!offset}
            onClick={() => setOffset(Math.max(0, offset - 20))}
          >
            Предыдущие совпадения
          </button>
          <button
            className="outline"
            disabled={offset + 20 >= data.total}
            onClick={() => setOffset(offset + 20)}
          >
            Следующие совпадения
          </button>
        </footer>
      )}
    </dialog>
  );
}
