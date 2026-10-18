import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { scopedRequest, type Doc } from "./api";
import { ProcessStatus } from "./ProcessStatus";

type Page = { items: Doc[]; total: number };
type Preview = { document: Doc; text: string; offset: number; total: number };

export function DocumentPanel({
  conversationId,
  projectName,
  selected,
  disabled,
  onToggle,
  onChanged,
  onChat,
  onError,
}: {
  conversationId: string;
  projectName?: string;
  selected: string[];
  disabled: boolean;
  onToggle: (doc: Doc) => void;
  onChanged: () => Promise<void>;
  onChat: () => void;
  onError: (error: unknown) => void;
}) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("all");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<Page>({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [reading, setReading] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [destination, setDestination] = useState("chat");
  const [notice, setNotice] = useState("");
  const epoch = useRef(0),
    readEpoch = useRef(0),
    mounted = useRef(true);
  const fileInput = useRef<HTMLInputElement>(null);
  const report = useRef(onError);
  report.current = onError;
  const load = useCallback(async () => {
    const ticket = ++epoch.current;
    setLoading(true);
    try {
      const result = await request<Page>(
        "/documents/library?" +
          new URLSearchParams({ q: search, scope, offset: String(offset) }),
      );
      if (mounted.current && ticket === epoch.current) {
        if (offset > 0 && result.total <= offset)
          setOffset(Math.max(0, Math.floor((result.total - 1) / 20) * 20));
        else setData(result);
      }
    } catch (error) {
      if (mounted.current && ticket === epoch.current) report.current(error);
    } finally {
      if (mounted.current && ticket === epoch.current) setLoading(false);
    }
  }, [request, search, scope, offset]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      ++epoch.current;
      ++readEpoch.current;
    };
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const changed = () => {
      ++readEpoch.current;
      setPreview(null);
      setReading(false);
      void load();
    };
    const channel = new BroadcastChannel("wiley-ui");
    channel.onmessage = (event) => {
      if (event.data.type === "documents-changed") changed();
    };
    return () => channel.close();
  }, [load]);
  async function run(action: () => Promise<void>) {
    setWorking(true);
    setNotice("");
    try {
      await action();
      if (mounted.current) {
        await onChanged();
        await load();
      }
    } catch (error) {
      if (mounted.current) report.current(error);
    } finally {
      if (mounted.current) setWorking(false);
    }
  }
  async function read(doc: Doc, offset = 0) {
    const ticket = ++readEpoch.current;
    setReading(true);
    try {
      const result = await request<Preview>(
        "/documents/" + doc.id + "/text?offset=" + offset,
      );
      if (mounted.current && ticket === readEpoch.current) setPreview(result);
    } catch (error) {
      if (mounted.current && ticket === readEpoch.current)
        report.current(error);
    } finally {
      if (mounted.current && ticket === readEpoch.current) setReading(false);
    }
  }
  return (
    <section className="page scroll-page document-page">
      {working && (
        <ProcessStatus kind="document" label="Обрабатываю документ…" compact />
      )}
      <div className="page-heading compact">
        <div>
          <h1>Документы</h1>
          <p>
            {projectName
              ? "Чат и библиотека проекта «" + projectName + "»"
              : "Документы текущего чата"}
          </p>
        </div>
        <button
          className="outline"
          disabled={disabled || !selected.length}
          onClick={onChat}
        >
          К вопросу · {selected.length}/10
        </button>
      </div>
      <p className="help">
        При отправке вопроса модель получает фрагменты выбранных файлов. Поиск и
        просмотр работают локально. TXT, MD, CSV, текстовые PDF и DOCX; до 15
        МБ. Сканам нужен OCR, который пока не подключён.
      </p>
      <form
        className="card document-upload"
        onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            if (!file) return;
            const data = new FormData();
            data.append("file", file);
            const doc = await request<Doc>(
              "/documents?destination=" + destination,
              "POST",
              data,
            );
            if (mounted.current) {
              if (selected.length < 10) onToggle(doc);
              setFile(null);
              if (fileInput.current) fileInput.current.value = "";
              setNotice(
                selected.length < 10
                  ? "Документ прикреплён к чату. Можно задать вопрос."
                  : "Документ загружен. Уже прикреплено 10 файлов — уберите один и выберите новый.",
              );
            }
          });
        }}
      >
        <label>
          Добавить файл
          <input
            ref={fileInput}
            type="file"
            accept=".txt,.md,.csv,.pdf,.docx"
            required
            disabled={disabled || working}
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
        </label>
        <label>
          Загрузить в
          <select
            value={destination}
            disabled={disabled || working}
            onChange={(event) => setDestination(event.target.value)}
          >
            <option value="chat">Только этот чат</option>
            <option value="project" disabled={!projectName}>
              Библиотеку проекта
            </option>
          </select>
        </label>
        <button className="primary" disabled={disabled || working || !file}>
          Загрузить документ
        </button>
      </form>
      <form
        className="document-search"
        onSubmit={(event) => {
          event.preventDefault();
          setOffset(0);
          setSearch(query.trim());
        }}
      >
        <label>
          Найти в документах
          <input
            type="search"
            maxLength={200}
            placeholder="Название или слова из текста"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label>
          Показывать документы
          <select
            value={scope}
            onChange={(event) => {
              setScope(event.target.value);
              setOffset(0);
            }}
          >
            <option value="all">Все доступные</option>
            <option value="chat">Только этот чат</option>
            <option value="project" disabled={!projectName}>
              Только проект
            </option>
          </select>
        </label>
        <button className="outline">Найти</button>
        <button className="subtle" type="button" onClick={() => void load()}>
          Обновить
        </button>
      </form>
      {notice && <p role="status">{notice}</p>}
      {reading && <p role="status">Читаю документ…</p>}
      {preview && (
        <article className="card document-preview">
          <div className="button-row">
            <h2>{preview.document.name}</h2>
            <button
              className="subtle"
              onClick={() => {
                ++readEpoch.current;
                setPreview(null);
                setReading(false);
              }}
            >
              Закрыть просмотр
            </button>
          </div>
          <p className="help">
            Извлечённый текст · символы {preview.offset + 1}–
            {preview.offset + preview.text.length} из {preview.total}
          </p>
          <pre>{preview.text}</pre>
          <div className="button-row">
            <button
              className="outline"
              disabled={reading || preview.offset === 0}
              onClick={() =>
                void read(preview.document, Math.max(0, preview.offset - 12000))
              }
            >
              Предыдущий фрагмент
            </button>
            <button
              className="outline"
              disabled={
                reading || preview.offset + preview.text.length >= preview.total
              }
              onClick={() =>
                void read(
                  preview.document,
                  preview.offset + preview.text.length,
                )
              }
            >
              Следующий фрагмент
            </button>
          </div>
        </article>
      )}
      {loading ? (
        <ProcessStatus kind="search" label="Ищу документы…" compact />
      ) : (
        <>
          <p className="help">
            Найдено: {data.total}. Выбрано для вопроса: {selected.length}/10.
            Поиск по словам и их началам; все слова запроса должны
            присутствовать.
          </p>
          <div className="document-results">
            {data.items.map((doc) => (
              <article className="card document-entry" key={doc.id}>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={selected.includes(doc.id)}
                    disabled={
                      disabled ||
                      working ||
                      (!selected.includes(doc.id) && selected.length >= 10)
                    }
                    onChange={() => onToggle(doc)}
                  />
                  Выбрать «{doc.name}» для вопроса
                </label>
                <h2>{doc.name}</h2>
                <small>
                  {doc.scope === "project"
                    ? "Документ проекта · доступен всем его чатам"
                    : "Только этот чат"}{" "}
                  · {doc.characters.toLocaleString("ru-RU")} символов
                </small>
                <p className="document-excerpt">{doc.preview}</p>
                <div className="button-row">
                  <button className="subtle" onClick={() => void read(doc)}>
                    Просмотреть текст
                  </button>
                  {projectName && doc.scope === "chat" && (
                    <button
                      className="subtle"
                      disabled={disabled || working}
                      onClick={() =>
                        void run(async () => {
                          await request(
                            "/documents/" + doc.id + "/publish",
                            "POST",
                          );
                          if (mounted.current)
                            setNotice(
                              "Создана отдельная копия для всех чатов проекта. Исходный файл чата сохранён.",
                            );
                        })
                      }
                    >
                      Создать копию для проекта
                    </button>
                  )}
                  <button
                    className="subtle danger"
                    disabled={disabled || working}
                    onClick={() =>
                      void run(async () => {
                        await request("/documents/" + doc.id, "DELETE");
                        ++readEpoch.current;
                        if (mounted.current) {
                          setPreview(null);
                          setReading(false);
                          setNotice(
                            doc.scope === "project"
                              ? "Документ удалён из библиотеки всех чатов проекта"
                              : "Документ удалён из чата",
                          );
                        }
                      })
                    }
                  >
                    {doc.scope === "project"
                      ? "Удалить из проекта"
                      : "Удалить из чата"}
                  </button>
                </div>
              </article>
            ))}
          </div>
          {!data.total && (
            <p>Документы не найдены. Загрузите файл или измените запрос.</p>
          )}
          <div className="button-row">
            <button
              className="outline"
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Предыдущие документы
            </button>
            <button
              className="outline"
              disabled={offset + 20 >= data.total}
              onClick={() => setOffset(offset + 20)}
            >
              Следующие документы
            </button>
          </div>
        </>
      )}
    </section>
  );
}
