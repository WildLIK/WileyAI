import { memo, useSyncExternalStore } from "react";
import type { Message, ReadingProgress } from "./api";
import type { AnswerStore } from "./answerStore";
import type { HistoryFocus } from "./ChatMessages";
import { historyParts } from "./historyText";
import { SearchSources } from "./WebSearch";
import { DocumentContext } from "./DocumentContext";
import { ProcessStatus } from "./ProcessStatus";
import { DocumentReadingProgress } from "./DocumentReadingProgress";

const timeFormat = new Intl.DateTimeFormat("ru-RU", {
  hour: "2-digit",
  minute: "2-digit",
});
const stamp = (value: string) => timeFormat.format(new Date(value));

/** One chat message. Callbacks must be stable so the list skips unchanged rows. */
export const MessageItem = memo(function MessageItem({
  message,
  name,
  focus,
  speakDisabled,
  continuable,
  continueDisabled,
  limit,
  onSpeak,
  onContinue,
  onError,
  onNotice,
}: {
  message: Message;
  name: string;
  focus: HistoryFocus | null;
  speakDisabled: boolean;
  /** Only the last complete answer can be continued. */
  continuable: boolean;
  continueDisabled: boolean;
  limit: string;
  onSpeak: (text: string) => void;
  onContinue: () => void;
  onError: (error: unknown) => void;
  onNotice: (text: string) => void;
}) {
  return (
    <article
      className={"message " + message.role + (focus ? " history-hit" : "")}
      data-message-id={message.id}
      tabIndex={focus ? -1 : undefined}
    >
      <div className="message-avatar">
        {message.role === "user" ? "Вы" : "W"}
      </div>
      <div className="message-body">
        <div className="message-meta">
          {message.role === "user" ? "Вы" : name}
          <time>{stamp(message.created)}</time>
          {message.role === "assistant" && (
            <button
              className="speak-button"
              aria-label="Озвучить ответ"
              disabled={speakDisabled}
              onClick={() => onSpeak(message.content)}
            >
              ♪
            </button>
          )}
        </div>
        <div className="message-text">
          {focus
            ? historyParts(message.content, focus.terms).map((part, index) =>
                part.match ? (
                  <mark data-history-match key={index}>
                    {part.text}
                  </mark>
                ) : (
                  part.text
                ),
              )
            : message.content}
        </div>
        {continuable && (
          <div className="button-row">
            <button
              className="subtle"
              disabled={continueDisabled}
              onClick={onContinue}
            >
              Продолжить ответ
            </button>
            {limit && <small role="status">{limit}</small>}
          </div>
        )}
        <SearchSources
          message={message}
          onError={onError}
          onNotice={onNotice}
        />
        <DocumentContext message={message} />
        {Boolean(message.memory_context?.length) && (
          <details className="memory-context">
            <summary>Передано в контекст из памяти</summary>
            <ul>
              {message.memory_context!.map((item) => (
                <li key={item.id}>{item.content}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </article>
  );
});

/** The answer being generated; only this view re-renders for streamed text. */
export function StreamingAnswer({
  store,
  name,
  stage,
  readingProgress,
  onStop,
}: {
  store: AnswerStore;
  name: string;
  stage: string;
  readingProgress: ReadingProgress | null;
  onStop: () => void;
}) {
  const answer = useSyncExternalStore(store.subscribe, store.get);
  return (
    <article className="message assistant" aria-busy="true">
      <div className="message-avatar">W</div>
      <div className="message-body">
        <div className="message-meta">
          {name}
          <span className="thinking">{stage}</span>
        </div>
        <div className="message-text">
          <ProcessStatus
            kind={
              readingProgress
                ? "document"
                : /ищу|поиск/i.test(stage)
                  ? "search"
                  : "brain"
            }
            label={stage || "Готовлю ответ…"}
            detail={
              answer
                ? "Ответ появляется по мере готовности"
                : "Обрабатываю запрос"
            }
            compact={Boolean(answer)}
          />
          {readingProgress && (
            <DocumentReadingProgress value={readingProgress} onStop={onStop} />
          )}
          {answer}
        </div>
      </div>
    </article>
  );
}
