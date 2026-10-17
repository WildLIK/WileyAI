import type { ReadingProgress } from "./api";

export function DocumentReadingProgress({
  value,
  onStop,
}: {
  value: ReadingProgress;
  onStop: () => void;
}) {
  const writing = value.phase === "answering";
  const starting = !writing && value.current === 0;
  const percent = Math.min(
    100,
    Math.max(0, (value.current / Math.max(1, value.total)) * 100),
  );
  return (
    <div className="document-reading-progress">
      <div className="document-reading-heading">
        <span role="status">{value.text}</span>
        <button
          type="button"
          className="subtle"
          aria-label="Остановить чтение документа"
          onClick={onStop}
        >
          ■ Остановить
        </button>
      </div>
      <div
        className={
          "document-reading-track" +
          (writing ? " indeterminate" : starting ? " starting" : "")
        }
        role="progressbar"
        aria-label={value.text}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={writing || starting ? undefined : Math.round(percent)}
      >
        <span
          style={{ width: writing ? "100%" : starting ? "30%" : percent + "%" }}
        />
      </div>
      <small>
        {writing
          ? "Готовлю итоговый ответ"
          : `${value.current} / ${value.total} · ${Math.round(percent)}% текущего этапа`}
      </small>
    </div>
  );
}
