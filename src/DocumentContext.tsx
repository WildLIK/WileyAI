import type { Message } from "./api";

export function DocumentContext({ message }: { message: Message }) {
  if (!message.document_context?.length) return null;
  return (
    <details className="document-context">
      <summary>
        Документы в контексте · {message.document_context.length}
      </summary>
      <p className="help">
        Текст, выбранный для этой реплики. Диапазоны показывают, какая часть
        документа попала в контекст.
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
  );
}
