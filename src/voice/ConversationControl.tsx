import { phaseLabels, type ConversationState } from "./conversation";

export function ConversationControl({
  state,
  onToggle,
  onInterrupt,
  compact = false,
  disabled = false,
  speaking = false,
}: {
  state: ConversationState;
  onToggle: () => void;
  onInterrupt: () => void;
  compact?: boolean;
  disabled?: boolean;
  speaking?: boolean;
}) {
  return (
    <div
      className={
        "conversation-control " +
        (state.active ? "enabled " : "") +
        (compact ? "compact" : "")
      }
    >
      <button
        className={state.active ? "outline conversation-end" : "outline"}
        disabled={disabled && !state.active}
        onClick={onToggle}
        aria-label={state.active ? "Завершить разговор" : "Начать разговор"}
      >
        {state.active ? "■ Завершить разговор" : "◉ Начать разговор"}
      </button>
      {state.active && (
        <>
          <span className="conversation-phase" role="status">
            <i />
            {state.owner ? phaseLabels[state.phase] : "Разговор в другом окне"}
          </span>
        </>
      )}
      {(speaking ||
        (state.active &&
          ["transcribing", "thinking", "speaking"].includes(state.phase))) && (
        <button
          className="outline speech-stop"
          onClick={onInterrupt}
          title="Escape — остановить; Ctrl+Shift+Esc — из любого приложения"
        >
          {speaking ? "■ Остановить озвучку" : "Перебить"}
        </button>
      )}
    </div>
  );
}
