import { useEffect, useState } from "react";
import { request, scoped, errorText } from "./api";

type Receipt = {
  id: string;
  created: string;
  steps: {
    step: number;
    domain: string;
    action: string;
    title: string;
    result: string;
  }[];
};
const domains: Record<string, string> = {
  task: "Задача",
  note: "Заметка",
  event: "Календарь",
};
const actions: Record<string, string> = {
  create: "создание",
  move: "перенос",
  delete: "удаление",
  complete: "завершение",
  stop: "остановка серии",
  resume: "возобновление серии",
  no_repeat: "отмена повтора",
  update: "замена текста",
  append: "дополнение",
};

export function PlanHistory({
  conversationId,
  scopeName,
}: {
  conversationId: string;
  scopeName: string;
}) {
  const [items, setItems] = useState<Receipt[]>([]),
    [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void request<Receipt[]>(
      scoped("/plans/history", conversationId),
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) {
          setItems(value);
          setError("");
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorText(err));
      });
    return () => controller.abort();
  }, [conversationId, revision]);
  useEffect(() => {
    const changed = () => setRevision((value) => value + 1);
    window.addEventListener("wiley-data-updated", changed);
    return () => window.removeEventListener("wiley-data-updated", changed);
  }, []);
  return (
    <section className="card" aria-label="Результаты планов из чата">
      <h2>Планы из чата</h2>
      <p>
        {scopeName}. До шести локальных действий над задачами, заметками и
        календарём. Сначала WileyAI покажет весь план и попросит подтверждение.
      </p>
      <p>
        Пример: «Напомни завтра в 10 оплатить интернет; запиши заметку
        Документы: забрать паспорт». Сохранённые результаты появляются здесь.
      </p>
      <button
        className="outline"
        onClick={() => setRevision((value) => value + 1)}
      >
        Обновить результаты планов
      </button>
      {error && <p role="alert">{error}</p>}
      {!items.length && <p>Выполненных планов в этом пространстве пока нет.</p>}
      {items.map((item) => (
        <details key={item.id} className="plan-receipt">
          <summary>
            {new Date(item.created).toLocaleString("ru-RU")} · Сохранено
            действий: {item.steps.length}
          </summary>
          <ol>
            {item.steps.map((step) => (
              <li key={step.step}>
                {domains[step.domain]} · {actions[step.action]} · «{step.title}»
                —{" "}
                {step.result === "verified"
                  ? "результат проверен"
                  : step.result}
                .
              </li>
            ))}
          </ol>
        </details>
      ))}
    </section>
  );
}
