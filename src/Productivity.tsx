import { useEffect, useState } from "react";
import { request } from "./api";

type Task = {
  id: string;
  title: string;
  kind: string;
  due: string | null;
  done: boolean;
  created: string;
};
type Note = { id: string; title: string; content: string; created: string };
type Capability = {
  id: string;
  name: string;
  status: string;
  description: string;
  scopes: string[];
  adapters: string[];
};
const kinds: Record<string, string> = {
  todo: "Задача",
  reminder: "Напоминание",
  timer: "Таймер",
  alarm: "Будильник",
};

export function Productivity({
  mode,
  onError,
}: {
  mode: "tasks" | "notes";
  onError: (error: unknown) => void;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("todo");
  const [due, setDue] = useState("");
  const [minutes, setMinutes] = useState(5);
  const [editing, setEditing] = useState<string | null>(null);
  const load = async () => {
    if (mode === "tasks") setTasks(await request("/tasks"));
    else setNotes(await request("/notes"));
  };
  useEffect(() => {
    setTitle("");
    setContent("");
    setDue("");
    setEditing(null);
    void load().catch(onError);
  }, [mode]);
  const run = async (action: () => Promise<void>) => {
    try {
      await action();
    } catch (error) {
      onError(error);
    }
  };
  async function save() {
    if (mode === "notes") {
      await request(
        editing ? "/notes/" + editing : "/notes",
        editing ? "PUT" : "POST",
        { title, content },
      );
    } else {
      const timestamp =
        kind === "timer"
          ? new Date(Date.now() + minutes * 60000).toISOString()
          : due
            ? new Date(due).toISOString()
            : null;
      await request(
        editing ? "/tasks/" + editing : "/tasks",
        editing ? "PUT" : "POST",
        { title, kind, due: timestamp, done: false },
      );
    }
    setTitle("");
    setContent("");
    setDue("");
    setEditing(null);
    await load();
  }
  function editTask(task: Task) {
    setEditing(task.id);
    setTitle(task.title);
    setKind(task.kind);
    if (task.due) {
      const date = new Date(task.due);
      setDue(
        new Date(date.getTime() - date.getTimezoneOffset() * 60000)
          .toISOString()
          .slice(0, 16),
      );
    } else setDue("");
  }
  return (
    <section className="page scroll-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">ПОРЯДОК В ДЕЛАХ</span>
          <h1>
            {mode === "tasks" ? "Задачи и напоминания" : "Заметки и списки"}
          </h1>
          <p>
            {mode === "tasks"
              ? "Локальные дела, таймеры и уведомления без облака."
              : "Мысли, идеи и списки остаются на вашем компьютере."}
          </p>
        </div>
      </div>
      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          void run(save);
        }}
      >
        <h2>
          {editing
            ? "Редактирование"
            : mode === "tasks"
              ? "Новое дело"
              : "Новая заметка"}
        </h2>
        <label>
          Название
          <input
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={mode === "tasks" ? "Купить хлеб" : "Идеи для проекта"}
          />
        </label>
        {mode === "notes" ? (
          <label>
            Содержание
            <textarea
              rows={5}
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder={"- Первый пункт\n- Второй пункт"}
            />
          </label>
        ) : (
          <div className="two-columns">
            <label>
              Тип
              <select
                value={kind}
                onChange={(event) => setKind(event.target.value)}
              >
                {Object.entries(kinds).map(([id, label]) => (
                  <option value={id} key={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {kind === "timer" ? (
              <label>
                Через сколько минут
                <input
                  type="number"
                  min={1}
                  max={10080}
                  value={minutes}
                  onChange={(event) => setMinutes(Number(event.target.value))}
                  required
                />
              </label>
            ) : (
              <label>
                Дата и время{kind === "todo" ? " (необязательно)" : ""}
                <input
                  type="datetime-local"
                  required={kind !== "todo"}
                  value={due}
                  onChange={(event) => setDue(event.target.value)}
                />
              </label>
            )}
          </div>
        )}
        <div className="button-row">
          <button className="primary" disabled={!title.trim()}>
            {editing ? "Сохранить изменения" : "Добавить"}
          </button>
          {editing && (
            <button
              type="button"
              className="outline"
              onClick={() => {
                setEditing(null);
                setTitle("");
                setContent("");
                setDue("");
              }}
            >
              Отмена
            </button>
          )}
        </div>
        {mode === "tasks" && (
          <p className="help">
            Уведомления работают, пока WileyAI запущен, в том числе в трее.
            Пропущенные срабатывают при следующем запуске. Время устройства:{" "}
            {Intl.DateTimeFormat().resolvedOptions().timeZone}. Повторяющиеся
            события пока не поддерживаются.
          </p>
        )}
      </form>
      {mode === "tasks" ? (
        <div className="card">
          <h2>Мои дела</h2>
          {tasks.map((task) => (
            <div
              className={"alias-row " + (task.done ? "task-done" : "")}
              key={task.id}
            >
              <div>
                <strong>{task.title}</strong>
                <small>
                  {kinds[task.kind]}
                  {task.due
                    ? " · " + new Date(task.due).toLocaleString("ru-RU")
                    : ""}
                  {task.done ? " · выполнено" : ""}
                </small>
              </div>
              <div className="button-row">
                <button
                  className="subtle"
                  onClick={() =>
                    run(async () => {
                      await request("/tasks/" + task.id, "PUT", {
                        ...task,
                        done: !task.done,
                      });
                      await load();
                    })
                  }
                >
                  {task.done ? "Вернуть" : "Готово"}
                </button>
                <button className="subtle" onClick={() => editTask(task)}>
                  Изменить
                </button>
                <button
                  className="subtle danger"
                  onClick={() =>
                    run(async () => {
                      await request("/tasks/" + task.id, "DELETE");
                      await load();
                    })
                  }
                >
                  Удалить
                </button>
              </div>
            </div>
          ))}
          {!tasks.length && <p>Начните с одного небольшого дела.</p>}
        </div>
      ) : (
        <div className="model-grid">
          {notes.map((note) => (
            <article className="card" key={note.id}>
              <h2>{note.title}</h2>
              <p className="note-content">{note.content}</p>
              <div className="button-row">
                <button
                  className="subtle"
                  onClick={() => {
                    setEditing(note.id);
                    setTitle(note.title);
                    setContent(note.content);
                  }}
                >
                  Изменить
                </button>
                <button
                  className="subtle danger"
                  onClick={() =>
                    run(async () => {
                      await request("/notes/" + note.id, "DELETE");
                      await load();
                    })
                  }
                >
                  Удалить
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export function Capabilities({
  onError,
}: {
  onError: (error: unknown) => void;
}) {
  const [items, setItems] = useState<Capability[]>([]);
  useEffect(() => {
    void request<Capability[]>("/capabilities").then(setItems).catch(onError);
  }, []);
  return (
    <section className="page scroll-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">РАСШИРЯЕМАЯ ПЛАТФОРМА</span>
          <h1>Возможности</h1>
          <p>Все направления развития и их фактическая готовность.</p>
        </div>
      </div>
      <div className="model-grid">
        {items.map((item) => (
          <article className="model-card capability-card" key={item.id}>
            <div className="model-card-top">
              <span
                className={
                  "kind " + (item.status === "available" ? "llm" : "stt")
                }
              >
                {
                  {
                    available: "ДОСТУПНО",
                    partial: "ЧАСТИЧНО",
                    planned: "ЗАПЛАНИРОВАНО",
                  }[item.status]
                }
              </span>
            </div>
            <h2>{item.name}</h2>
            <p>{item.description}</p>
            {item.adapters.length > 0 && (
              <div className="model-properties">
                {item.adapters.map((adapter) => (
                  <span key={adapter}>{adapter}</span>
                ))}
              </div>
            )}
            <details>
              <summary>Области разрешений для адаптера</summary>
              <p className="help">{item.scopes.join(" · ")}</p>
            </details>
          </article>
        ))}
      </div>
    </section>
  );
}
