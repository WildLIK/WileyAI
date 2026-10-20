import { useEffect, useState } from "react";
import { scopedRequest, type Memory, type MemoryCandidate } from "./api";

const categories = {
  fact: "Факт",
  preference: "Предпочтение",
  profile: "Занятие / проект",
};
type Shared = {
  conversationId: string;
  memories: Memory[];
  candidates: MemoryCandidate[];
  onChanged: () => Promise<void>;
  onError: (error: unknown) => void;
};

function Suggestion({
  conversationId,
  item,
  memories,
  onChanged,
  onError,
}: Omit<Shared, "candidates"> & { item: MemoryCandidate }) {
  const request = scopedRequest(conversationId);
  const [text, setText] = useState(item.content);
  const [category, setCategory] = useState(item.category);
  const [replace, setReplace] = useState("");
  const [pending, setPending] = useState(false);
  async function decide(accept: boolean) {
    setPending(true);
    try {
      await request(
        "/memory-candidates/" + item.id + (accept ? "/accept" : ""),
        accept ? "POST" : "DELETE",
        accept ? { text, category, replace_id: replace || null } : undefined,
      );
      await onChanged();
    } catch (error) {
      onError(error);
    } finally {
      setPending(false);
    }
  }
  return (
    <article className="memory-suggestion">
      <label>
        Предложение памяти
        <textarea
          aria-label="Текст предложения памяти"
          maxLength={1200}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      <div className="two-columns">
        <label>
          Категория
          <select
            aria-label="Категория предложения"
            value={category}
            onChange={(event) =>
              setCategory(event.target.value as Memory["category"])
            }
          >
            {Object.entries(categories).map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
        {memories.length > 0 && (
          <label>
            Как сохранить
            <select
              aria-label="Заменить запись памяти"
              value={replace}
              onChange={(event) => setReplace(event.target.value)}
            >
              <option value="">Отдельной записью</option>
              {memories.map((memory) => (
                <option key={memory.id} value={memory.id}>
                  Заменить: {memory.content.slice(0, 110)}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <details>
        <summary>Исходная реплика</summary>
        <blockquote>{item.source_text}</blockquote>
      </details>
      <div className="button-row">
        <button
          className="outline"
          disabled={pending || !text.trim()}
          onClick={() => void decide(true)}
        >
          {replace ? "Принять и заменить" : "Принять в память"}
        </button>
        <button
          className="subtle"
          disabled={pending}
          onClick={() => void decide(false)}
        >
          Отклонить
        </button>
      </div>
    </article>
  );
}

export function MemorySuggestions({
  compact = false,
  onOpen,
  ...props
}: Shared & { compact?: boolean; onOpen?: () => void }) {
  if (!props.candidates.length) return null;
  return (
    <div className={"card memory-suggestions " + (compact ? "compact" : "")}>
      <div className="memory-suggestions-heading">
        <h2>Предложения памяти · {props.candidates.length}</h2>
        {compact && (
          <button className="subtle" onClick={onOpen}>
            Вся память
          </button>
        )}
      </div>
      <p className="help">
        Эти предложения ещё не приняты и не передаются как постоянная память.
        Проверьте текст и источник перед принятием.
      </p>
      {props.candidates.slice(0, compact ? 2 : 50).map((item) => (
        <Suggestion
          key={item.id}
          item={item}
          conversationId={props.conversationId}
          memories={props.memories}
          onChanged={props.onChanged}
          onError={props.onError}
        />
      ))}
    </div>
  );
}

function MemoryRecord({
  conversationId,
  item,
  onChanged,
  onError,
}: {
  conversationId: string;
  item: Memory;
  onChanged: Shared["onChanged"];
  onError: Shared["onError"];
}) {
  const request = scopedRequest(conversationId);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(item.content);
  const [category, setCategory] = useState(item.category);
  const [pending, setPending] = useState(false);
  async function save(pinned = Boolean(item.pinned)) {
    setPending(true);
    try {
      await request("/memories/" + item.id, "PUT", { text, category, pinned });
      setEditing(false);
      await onChanged();
    } catch (error) {
      onError(error);
    } finally {
      setPending(false);
    }
  }
  async function remove() {
    setPending(true);
    try {
      await request("/memories/" + item.id, "DELETE");
      await onChanged();
    } catch (error) {
      onError(error);
    } finally {
      setPending(false);
    }
  }
  useEffect(() => {
    if (!editing) {
      setText(item.content);
      setCategory(item.category);
    }
  }, [item.content, item.category, editing]);
  return (
    <article className="card memory-entry">
      {editing ? (
        <>
          <label>
            Текст записи
            <textarea
              aria-label="Текст записи памяти"
              maxLength={1200}
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <label>
            Категория
            <select
              aria-label="Категория записи"
              value={category}
              onChange={(event) =>
                setCategory(event.target.value as Memory["category"])
              }
            >
              {Object.entries(categories).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              className="outline"
              disabled={pending || !text.trim()}
              onClick={() => void save()}
            >
              Сохранить запись
            </button>
            <button className="subtle" onClick={() => setEditing(false)}>
              Отмена
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="memory-content">{item.content}</p>
          <small>
            {categories[item.category]} · {item.pinned ? "Закреплено · " : ""}
            {new Date(item.updated || item.created).toLocaleDateString("ru-RU")}
          </small>
          <div className="button-row">
            <button
              className="subtle"
              disabled={pending}
              onClick={() => setEditing(true)}
            >
              Изменить
            </button>
            <button
              className="subtle"
              disabled={pending}
              onClick={() => void save(!item.pinned)}
            >
              {item.pinned ? "Открепить" : "Закрепить"}
            </button>
            <button
              className="subtle danger"
              disabled={pending}
              aria-label={"Удалить запись " + item.content}
              onClick={() => void remove()}
            >
              Удалить
            </button>
          </div>
        </>
      )}
      {item.source_text && (
        <details>
          <summary>Источник записи</summary>
          <blockquote>{item.source_text}</blockquote>
        </details>
      )}
    </article>
  );
}

export function MemoryPanel(
  props: Shared & { suggestionsEnabled: boolean; scopeName: string },
) {
  const request = scopedRequest(props.conversationId);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState(props.memories);
  const [searchNotice, setSearchNotice] = useState("");
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (!query.trim()) {
      setMatches(props.memories);
      setSearchNotice("");
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      request<{ items: Memory[]; mode: string; notice: string }>(
        "/memory-search?q=" + encodeURIComponent(query),
        "GET",
        undefined,
        controller.signal,
      )
        .then((result) => {
          setMatches(result.items);
          setSearchNotice(
            result.notice ||
              (result.mode === "semantic"
                ? "Результаты поиска по смыслу"
                : "Результаты поиска по словам"),
          );
        })
        .catch(props.onError);
    }, 200);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [query, props.memories]);
  async function add() {
    setPending(true);
    try {
      await request("/memories", "POST", { text: draft });
      setDraft("");
      await props.onChanged();
    } catch (error) {
      props.onError(error);
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="page scroll-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">УПРАВЛЯЕМАЯ ПАМЯТЬ</span>
          <h1>Что я помню о вас</h1>
          <strong className="scope-label">{props.scopeName}</strong>
          <p>Подтверждённые факты, предпочтения и контекст ваших проектов.</p>
          <p className="help">
            {props.suggestionsEnabled
              ? "Предложения из новых реплик включены."
              : "Предложения из разговоров выключены."}{" "}
            Это можно изменить в настройках. Удаление памяти не удаляет исходную
            переписку.
          </p>
        </div>
      </div>
      <MemorySuggestions {...props} />
      <form
        className="card memory-form"
        onSubmit={(event) => {
          event.preventDefault();
          void add();
        }}
      >
        <textarea
          aria-label="Новая запись памяти"
          placeholder="Например: я предпочитаю краткие ответы"
          maxLength={1200}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button className="primary" disabled={pending || !draft.trim()}>
          Запомнить
        </button>
      </form>
      {searchNotice && (
        <p className="help" role="status">
          {searchNotice}
        </p>
      )}
      <label className="memory-search">
        Поиск по памяти
        <input
          type="search"
          aria-label="Поиск по памяти"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Проект, привычка или предпочтение"
        />
      </label>
      <p className="help">
        При ответах Уайли учитывает подходящие записи, закреплённые факты и
        немного недавней памяти. Для поиска укажите слово или его начало.
      </p>
      <div className="memory-list">
        {matches.map((item) => (
          <MemoryRecord
            key={item.id}
            item={item}
            conversationId={props.conversationId}
            onChanged={props.onChanged}
            onError={props.onError}
          />
        ))}
      </div>
      {!matches.length && (
        <div className="empty-state">
          {query
            ? "По этому запросу записей нет."
            : "Добавьте факт вручную или примите предложение из разговора."}
        </div>
      )}
    </section>
  );
}
