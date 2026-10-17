import type { Message } from "./api";
import { documentCoverage } from "./documentCoverage";

export function DocumentContext({ message }: { message: Message }) {
  if (!message.document_context?.length) return null;
  const evidence = message.document_context.every(
    (source) => source.purpose === "summary_evidence",
  );
  const partial = documentCoverage(
    message.document_context.filter(
      (source) => source.purpose !== "summary_evidence",
    ),
  ).filter((item) => item.partial);
  return (
    <>
      {partial.length > 0 && (
        <p className="document-coverage">
          В этом ответе использованы отрывки:{" "}
          {partial
            .map(
              (item) =>
                `${item.name} — ${item.covered.toLocaleString("ru-RU")} из ${item.total.toLocaleString("ru-RU")} символов`,
            )
            .join("; ")}
          . Это не чтение файла целиком.
        </p>
      )}
      <details className="document-context">
        <summary>
          {evidence ? "Опорные фрагменты пересказа" : "Документы в контексте"} ·{" "}
          {message.document_context.length}
        </summary>
        <p className="help">
          {evidence
            ? "Номера [1], [2] в пересказе ссылаются на эти дословные отрывки. При чтении обработаны все части файла; здесь сохранены опоры для итогового ответа."
            : "Текст, выбранный для этой реплики. Диапазоны показывают, какая часть документа попала в контекст."}
        </p>
        <ol>
          {message.document_context.map((source, index) => (
            <li key={source.document_id + ":" + source.offset + ":" + index}>
              <strong>{source.name}</strong>
              <small>
                Символы {source.offset + 1}–
                {source.offset + [...source.text].length} из {source.total}
              </small>
              <blockquote>{source.text}</blockquote>
            </li>
          ))}
        </ol>
        <p className="help">
          Сохранённые отрывки остаются в переписке и резервной копии, даже если
          удалить файл из библиотеки.
        </p>
      </details>
    </>
  );
}
