import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { request, scopedRequest } from "./api";

type Task = {
  id: string;
  title: string;
  kind: string;
  due: string | null;
  done: boolean;
  created: string;
  recurrence: string | null;
};
type RepeatRule = {
  rule: "daily" | "weekdays" | "weekly";
  weekday?: number;
  weekdays?: number[];
  timezone?: string;
};
const weekdays = [
  "Понедельник",
  "Вторник",
  "Среда",
  "Четверг",
  "Пятница",
  "Суббота",
  "Воскресенье",
];
const dayShort = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
const deviceZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
function repeatRule(task: Task): RepeatRule | null {
  return task.recurrence ? JSON.parse(task.recurrence) : null;
}
function repeatLabel(task: Task) {
  try {
    const rule = repeatRule(task);
    if (!rule) return "";
    const days = rule.weekdays?.length ? rule.weekdays : [rule.weekday ?? 0];
    return (
      (rule.rule === "daily"
        ? "ежедневно"
        : rule.rule === "weekdays"
          ? "по будням"
          : "по " + days.map((day) => dayShort[day]).join(", ")) +
      " · " +
      (rule.timezone || "UTC")
    );
  } catch {
    return "Некорректное правило повтора";
  }
}
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
  conversationId,
}: {
  mode: "tasks" | "notes";
  onError: (error: unknown) => void;
  conversationId: string;
}) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [tasks, setTasks] = useState<Task[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("todo");
  const [due, setDue] = useState("");
  const [minutes, setMinutes] = useState(5);
  const [editing, setEditing] = useState<string | null>(null);
  const [repeat, setRepeat] = useState<"none" | RepeatRule["rule"]>("none");
  const [repeatDays, setRepeatDays] = useState<number[]>([
    (new Date().getDay() + 6) % 7,
  ]);
  const [repeatZone, setRepeatZone] = useState(deviceZone);
  const [taskDone, setTaskDone] = useState(false);
  const [working, setWorking] = useState(false);
  const busy = useRef(false);
  const channel = useRef<BroadcastChannel | null>(null);
  const load = useCallback(async () => {
    if (mode === "tasks") setTasks(await request("/tasks"));
    else setNotes(await request("/notes"));
  }, [mode, request]);
  useEffect(() => {
    setTitle("");
    setContent("");
    setDue("");
    setEditing(null);
    setRepeat("none");
    setRepeatZone(deviceZone);
    setTaskDone(false);
    void load().catch(onError);
  }, [mode, load]);
  useEffect(() => {
    const changed = () => {
      void load().catch(onError);
    };
    channel.current = new BroadcastChannel("wiley-ui");
    channel.current.onmessage = (event) => {
      if (["chat-updated", "productivity-changed"].includes(event.data.type))
        changed();
    };
    window.addEventListener("wiley-data-updated", changed);
    return () => {
      channel.current?.close();
      window.removeEventListener("wiley-data-updated", changed);
    };
  }, [load]);
  const run = async (action: () => Promise<void>) => {
    if (busy.current) return;
    busy.current = true;
    setWorking(true);
    try {
      await action();
      channel.current?.postMessage({ type: "productivity-changed" });
    } catch (error) {
      onError(error);
    } finally {
      busy.current = false;
      setWorking(false);
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
      if (repeat === "weekly" && !repeatDays.length)
        throw new Error("Выберите хотя бы один день повтора");
      const recurrence: RepeatRule | null =
        repeat === "none" || !["reminder", "alarm"].includes(kind)
          ? null
          : {
              rule: repeat,
              timezone: repeatZone,
              ...(repeat === "weekly" ? { weekdays: repeatDays } : {}),
            };
      if (due) {
        const parsed = new Date(due);
        if (!Number.isFinite(parsed.getTime()))
          throw new Error("Укажите корректную дату и время");
        const local = new Date(
          parsed.getTime() - parsed.getTimezoneOffset() * 60000,
        )
          .toISOString()
          .slice(0, 16);
        if (local !== due.slice(0, 16))
          throw new Error(
            "Это местное время пропускается при переводе часов. Выберите другое время.",
          );
      }
      const timestamp =
        kind === "timer"
          ? new Date(Date.now() + minutes * 60000).toISOString()
          : due
            ? new Date(due).toISOString()
            : null;
      await request(
        editing ? "/tasks/" + editing : "/tasks",
        editing ? "PUT" : "POST",
        { title, kind, due: timestamp, done: taskDone, recurrence },
      );
    }
    setTitle("");
    setContent("");
    setDue("");
    setEditing(null);
    setRepeat("none");
    setTaskDone(false);
    setRepeatZone(deviceZone);
    await load();
  }
  function editTask(task: Task) {
    let rule: RepeatRule | null;
    try {
      rule = repeatRule(task);
    } catch (error) {
      onError(error);
      return;
    }
    setEditing(task.id);
    setTitle(task.title);
    setKind(task.kind);
    setTaskDone(Boolean(task.done));
    setRepeat(rule?.rule || "none");
    setRepeatDays(
      rule?.weekdays?.length
        ? rule.weekdays
        : [rule?.weekday ?? (new Date().getDay() + 6) % 7],
    );
    setRepeatZone(rule?.timezone || deviceZone);
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
          <p className="help">
            {mode === "tasks"
              ? "Можно сказать: «напомни по будням в 9 проверить почту», «напомни по понедельникам и средам в 10 позвонить», затем «перенеси на 11»."
              : "Можно сказать в чате: «создай заметку Покупки: хлеб и молоко»."}
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
                aria-label="Тип"
                value={kind}
                onChange={(event) => {
                  setKind(event.target.value);
                  if (!["reminder", "alarm"].includes(event.target.value))
                    setRepeat("none");
                }}
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
                {repeat !== "none" ? "Ближайшее напоминание" : "Дата и время"}
                {kind === "todo" ? " (необязательно)" : ""}
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
        {mode === "tasks" && ["reminder", "alarm"].includes(kind) && (
          <div className="task-repeat">
            <label>
              Повтор
              <select
                aria-label="Повтор"
                value={repeat}
                onChange={(event) =>
                  setRepeat(event.target.value as typeof repeat)
                }
              >
                <option value="none">Не повторять</option>
                <option value="daily">Ежедневно</option>
                <option value="weekdays">По будням · пн–пт</option>
                <option value="weekly">По выбранным дням недели</option>
              </select>
            </label>
            {repeat === "weekly" && (
              <fieldset className="task-repeat-days">
                <legend>Дни повтора</legend>
                {weekdays.map((day, index) => (
                  <label className="checkbox" key={day}>
                    <input
                      type="checkbox"
                      checked={repeatDays.includes(index)}
                      onChange={(event) =>
                        setRepeatDays((days) =>
                          event.target.checked
                            ? [...days, index].sort()
                            : days.filter((value) => value !== index),
                        )
                      }
                    />
                    {day}
                  </label>
                ))}
              </fieldset>
            )}
            {repeat !== "none" && (
              <p className="help">
                Часовой пояс повтора: {repeatZone}. Ближайший срок задаётся по
                времени устройства; следующие сохраняют соответствующее время
                суток в поясе повтора. Редактирование меняет всю серию. По
                будням — пн–пт без учёта праздников.
                {repeatZone !== deviceZone && (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => setRepeatZone(deviceZone)}
                  >
                    Использовать {deviceZone}
                  </button>
                )}
              </p>
            )}
          </div>
        )}
        <div className="button-row">
          <button
            className="primary"
            disabled={
              working ||
              !title.trim() ||
              (repeat === "weekly" && !repeatDays.length)
            }
          >
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
                setRepeat("none");
                setTaskDone(false);
                setRepeatZone(deviceZone);
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
            {deviceZone}. Если пропущено несколько повторов, придёт одно
            уведомление, а следующий срок будет в будущем.
          </p>
        )}
      </form>
      {mode === "tasks" ? (
        <div className="card">
          <h2>Мои дела</h2>
          {tasks.map((task) => (
            <div
              role="group"
              aria-label={task.title}
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
                  {task.recurrence ? " · " + repeatLabel(task) : ""}
                  {task.done
                    ? task.recurrence
                      ? " · серия остановлена"
                      : " · выполнено"
                    : ""}
                </small>
              </div>
              <div className="button-row">
                <button
                  className="subtle"
                  onClick={() =>
                    run(async () => {
                      await request("/tasks/" + task.id, "PUT", {
                        title: task.title,
                        kind: task.kind,
                        due: task.due,
                        recurrence: repeatRule(task),
                        done: !task.done,
                      });
                      await load();
                    })
                  }
                >
                  {task.recurrence
                    ? task.done
                      ? "Возобновить серию"
                      : "Остановить серию"
                    : task.done
                      ? "Вернуть"
                      : "Готово"}
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
