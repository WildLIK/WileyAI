import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { scopedRequest } from "./api";

type Event = {
  id: string;
  title: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  location: string;
  description: string;
  reminder_minutes: number | null;
  updated: string;
  conflict: boolean;
};
type Schedule = { events: Event[]; total: number };
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const local = (date: Date) =>
  new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
const today = () => local(new Date()).slice(0, 10);
const shift = (day: string, count: number) => {
  const date = new Date(day + "T12:00");
  date.setDate(date.getDate() + count);
  return local(date).slice(0, 10);
};
const dateLabel = (day: string) =>
  new Date(day + "T12:00").toLocaleDateString("ru-RU", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
const timeLabel = (value: string) =>
  new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

export function CalendarPanel({
  conversationId,
  scopeName,
  onError,
}: {
  conversationId: string;
  scopeName: string;
  onError: (error: unknown) => void;
}) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [day, setDay] = useState(today);
  const [schedule, setSchedule] = useState<Schedule>({ events: [], total: 0 });
  const [editing, setEditing] = useState<Event | null>(null);
  const [title, setTitle] = useState("");
  const [start, setStart] = useState(today() + "T10:00");
  const [end, setEnd] = useState(today() + "T11:00");
  const [place, setPlace] = useState("");
  const [description, setDescription] = useState("");
  const [reminderEnabled, setReminderEnabled] = useState(false);
  const [reminderMinutes, setReminderMinutes] = useState("15");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState("");
  const epoch = useRef(0);
  const currentDay = useRef(day);
  currentDay.current = day;
  const report = useRef(onError);
  report.current = onError;
  const mounted = useRef(true);
  const channel = useRef<BroadcastChannel | null>(null);
  const load = useCallback(async () => {
    const ticket = ++epoch.current;
    setLoading(true);
    try {
      const query = new URLSearchParams({
        start: new Date(day + "T00:00").toISOString(),
        end: new Date(shift(day, 7) + "T00:00").toISOString(),
      });
      const value = await request<Schedule>("/calendar/events?" + query);
      if (
        mounted.current &&
        ticket === epoch.current &&
        currentDay.current === day
      )
        setSchedule(value);
    } catch (error) {
      if (
        mounted.current &&
        ticket === epoch.current &&
        currentDay.current === day
      )
        report.current(error);
    } finally {
      if (
        mounted.current &&
        ticket === epoch.current &&
        currentDay.current === day
      )
        setLoading(false);
    }
  }, [day, request]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      ++epoch.current;
    };
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const changed = () => {
      void load();
    };
    const bus = new BroadcastChannel("wiley-ui");
    channel.current = bus;
    bus.onmessage = (event) => {
      if (["chat-updated", "calendar-changed"].includes(event.data.type))
        changed();
    };
    window.addEventListener("wiley-data-updated", changed);
    return () => {
      bus.close();
      window.removeEventListener("wiley-data-updated", changed);
    };
  }, [load]);

  function clear(resetDay = day) {
    setEditing(null);
    setTitle("");
    setPlace("");
    setDescription("");
    setReminderEnabled(false);
    setReminderMinutes("15");
    setStart(resetDay + "T10:00");
    setEnd(resetDay + "T11:00");
  }
  async function run(action: () => Promise<void>) {
    setWorking(true);
    setNotice("");
    try {
      await action();
      if (mounted.current) {
        channel.current?.postMessage({ type: "calendar-changed" });
        await load();
      }
    } catch (error) {
      if (mounted.current) onError(error);
    } finally {
      if (mounted.current) setWorking(false);
    }
  }
  async function save() {
    const route = editing
      ? "/calendar/events/" +
        editing.id +
        "?expected_updated=" +
        encodeURIComponent(editing.updated)
      : "/calendar/events";
    // Send wall-clock time and IANA zone. The core rejects DST gaps and folds.
    await request(route, editing ? "PUT" : "POST", {
      title,
      starts_at:
        editing && start === local(new Date(editing.starts_at))
          ? editing.starts_at
          : start,
      ends_at:
        editing && end === local(new Date(editing.ends_at))
          ? editing.ends_at
          : end,
      timezone: zone,
      location: place,
      description,
      reminder_minutes: reminderEnabled ? Number(reminderMinutes) : null,
    });
    if (mounted.current) {
      clear(start.slice(0, 10));
      setNotice(editing ? "Событие изменено" : "Событие добавлено");
      setDay(start.slice(0, 10));
    }
  }
  const days = Array.from({ length: 7 }, (_, index) => shift(day, index));

  return (
    <section className="page scroll-page calendar-page">
      <div className="page-heading">
        <div>
          <h1>Календарь</h1>
          <p>
            {scopeName
              .replace("Память проекта", "Календарь проекта")
              .replace("Общая память", "Общий календарь")}{" "}
            · {zone}
          </p>
          <p className="help">
            Локальные события и напоминания. Google и Outlook не подключены.
          </p>
        </div>
      </div>
      <div className="calendar-layout">
        <form
          className="card calendar-form"
          onSubmit={(event) => {
            event.preventDefault();
            void run(save);
          }}
        >
          <h2>{editing ? "Изменить событие" : "Новое событие"}</h2>
          <fieldset disabled={working}>
            <label>
              Название события
              <input
                required
                maxLength={200}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Обсуждение проекта"
              />
            </label>
            <label>
              Начало
              <input
                type="datetime-local"
                required
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </label>
            <label>
              Окончание
              <input
                type="datetime-local"
                required
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </label>
            <label>
              Место
              <input
                maxLength={500}
                value={place}
                onChange={(event) => setPlace(event.target.value)}
                placeholder="Офис или ссылка на встречу"
              />
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={reminderEnabled}
                onChange={(event) => setReminderEnabled(event.target.checked)}
              />
              Напомнить о встрече
            </label>
            {reminderEnabled && (
              <label>
                За сколько минут до начала
                <input
                  type="number"
                  min={0}
                  max={10080}
                  step={1}
                  required
                  value={reminderMinutes}
                  onChange={(event) => setReminderMinutes(event.target.value)}
                />
                <small>0 — в начале встречи. До 7 дней заранее.</small>
              </label>
            )}
            <label>
              Описание
              <textarea
                rows={3}
                maxLength={10000}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <div className="button-row">
              <button className="primary" disabled={!title.trim()}>
                {editing ? "Сохранить событие" : "Добавить событие"}
              </button>
              {editing && (
                <button
                  type="button"
                  className="outline"
                  onClick={() => clear()}
                >
                  Отмена
                </button>
              )}
            </div>
          </fieldset>
          <p className="help">
            В чате: «создай встречу Обсуждение проекта завтра в 10 на 30 минут»,
            затем «перенеси встречу на 11». Без длительности — один час.
          </p>
          <p className="help">
            Уведомления работают, пока WileyAI запущен, включая трей.
            Пропущенные показываются до окончания встречи. Перенос обновляет
            время напоминания.
          </p>
          {notice && <p role="status">{notice}</p>}
        </form>
        <div className="card calendar-agenda">
          <h2>Расписание на 7 дней</h2>
          <div className="calendar-navigation">
            <button
              className="outline"
              disabled={working}
              aria-label="Предыдущие 7 дней"
              onClick={() => setDay(shift(day, -7))}
            >
              ←
            </button>
            <label>
              С даты
              <input
                type="date"
                required
                value={day}
                disabled={working}
                onChange={(event) => {
                  if (event.target.value) setDay(event.target.value);
                }}
              />
            </label>
            <button
              className="outline"
              disabled={working}
              aria-label="Следующие 7 дней"
              onClick={() => setDay(shift(day, 7))}
            >
              →
            </button>
            <button
              className="subtle"
              disabled={working}
              onClick={() => setDay(today())}
            >
              Сегодня
            </button>
          </div>
          <p className="help">
            {dateLabel(day)} — {dateLabel(shift(day, 6))}. Пересечения
            отмечаются внутри текущего пространства.
          </p>
          {loading ? (
            <p role="status">Загружаю расписание…</p>
          ) : (
            <>
              {schedule.total > schedule.events.length && (
                <p role="status">
                  Показаны первые {schedule.events.length} из {schedule.total}{" "}
                  событий. Выберите более позднюю дату для остальных.
                </p>
              )}
              {days.map((date) => {
                const items = schedule.events.filter((item) => {
                  const beginDay = local(new Date(item.starts_at)).slice(0, 10);
                  return beginDay === date || (date === day && beginDay < day);
                });
                return (
                  <section
                    className="calendar-day"
                    key={date}
                    aria-label={dateLabel(date)}
                  >
                    <h3>
                      {dateLabel(date)}
                      {date === today() ? " · сегодня" : ""}
                    </h3>
                    {!items.length && (
                      <p className="help">Нет начинающихся событий</p>
                    )}
                    {items.map((item) => (
                      <article className="calendar-event" key={item.id}>
                        <div>
                          <strong>{item.title}</strong>
                          <small>
                            {timeLabel(item.starts_at)} —{" "}
                            {timeLabel(item.ends_at)}
                          </small>
                          {item.reminder_minutes !== null && (
                            <small>
                              {item.reminder_minutes === 0
                                ? "Напоминание в начале встречи"
                                : "Напоминание за " +
                                  item.reminder_minutes +
                                  " мин. до начала"}
                            </small>
                          )}
                          {item.conflict ? (
                            <span className="calendar-conflict">
                              Пересечение по времени
                            </span>
                          ) : null}
                          {item.location && <p>{item.location}</p>}
                          {item.description && (
                            <p className="note-content">{item.description}</p>
                          )}
                        </div>
                        <div className="button-row">
                          <button
                            className="subtle"
                            disabled={working}
                            aria-label={"Изменить событие «" + item.title + "»"}
                            onClick={() => {
                              setEditing(item);
                              setTitle(item.title);
                              setStart(local(new Date(item.starts_at)));
                              setEnd(local(new Date(item.ends_at)));
                              setPlace(item.location);
                              setDescription(item.description);
                              setReminderEnabled(
                                item.reminder_minutes !== null,
                              );
                              setReminderMinutes(
                                String(item.reminder_minutes ?? 15),
                              );
                              setNotice("");
                            }}
                          >
                            Изменить
                          </button>
                          <button
                            className="subtle danger"
                            disabled={working}
                            aria-label={"Удалить событие «" + item.title + "»"}
                            onClick={() =>
                              void run(async () => {
                                await request(
                                  "/calendar/events/" +
                                    item.id +
                                    "?expected_updated=" +
                                    encodeURIComponent(item.updated),
                                  "DELETE",
                                );
                                if (mounted.current) {
                                  if (editing?.id === item.id) clear();
                                  setNotice("Событие удалено");
                                }
                              })
                            }
                          >
                            Удалить
                          </button>
                        </div>
                      </article>
                    ))}
                  </section>
                );
              })}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
