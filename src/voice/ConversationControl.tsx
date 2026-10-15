import { phaseLabels, type ConversationState } from "./conversation";

export function ConversationControl({
  state,
  onToggle,
  onInterrupt,
  compact = false,
  disabled = false,
}: {
  state: ConversationState;
  onToggle: () => void;
  onInterrupt: () => void;
  compact?: boolean;
  disabled?: boolean;
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
          {state.owner && ["thinking", "speaking"].includes(state.phase) && (
            <button className="subtle" onClick={onInterrupt}>
              Перебить
            </button>
          )}
        </>
      )}
    </div>
  );
}
