import type { VoiceDiagnostics } from "./endpoint";
import { eventLabels, reasonLabels, type VoiceEvent } from "./diagnostics";
import type { ReactNode } from "react";

export function VoiceStatus({ value, events = [], policy }: { value: VoiceDiagnostics | null; events?: VoiceEvent[]; policy?: ReactNode }) {
  if (!value && !events.length) return null;
  const reasons: Record<string, string> = { pause: "пауза", smart_complete: "Smart Turn: фраза завершена", silence_limit: "предел ожидания после речи", maximum: "предел длины реплики", no_speech: "ожидание без речи", too_short: "недостаточно подтверждённой речи" };
  const phases = { waiting: "ожидание речи", speech: "слышу речь", pause: "обнаружена пауза", checking: "проверяю завершение фразы" };
  const last = events.at(-1);
  const decision = [...events].reverse().find((event) => ["activation_accepted", "activation_rejected", "stt_rejected", "stt_empty"].includes(event.name));
  return <details className="voice-diagnostics" aria-label="Диагностика голосового диалога"><summary>Голос: {value ? value.engine + " · " + phases[value.phase] : "события"}{last ? " · " + eventLabels[last.name] : ""}</summary>
    {policy}
    {decision && <p>Последняя обработанная реплика: {eventLabels[decision.name]}{decision.reason ? " — " + (reasonLabels[decision.reason] || decision.reason) : ""}.</p>}
    <p>Последнее событие: {last ? eventLabels[last.name] + (last.reason ? " — " + (reasonLabels[last.reason] || last.reason) : "") : "ожидание"}. Здесь сохраняются только метаданные текущего сеанса, без аудио и полного транскрипта.</p>
    {value && <>
    <p>Уровень сигнала: {value.level.toFixed(4)} · Оценка VAD: {value.score === undefined ? "нет у RMS" : value.score.toFixed(3)} (выход модели, не процент уверенности)</p>
    <p>Реплика: {Math.round(value.durationMs)} мс · Пауза: {Math.round(value.silenceMs)} мс · Последняя речь: {value.lastVoiceAgoMs < 0 ? "ещё не обнаружена" : Math.round(value.lastVoiceAgoMs) + " мс назад"}</p>
    <p>Завершение: {reasons[value.reason || ""] || "ещё не завершена"} · STT: {value.sttMs === undefined ? "—" : value.sttMs + " мс"} · Ожидание перед озвучкой: {value.responseWaitMs === undefined ? "—" : value.responseWaitMs + " мс"}</p>
    <p>VAD, кадр: {value.vadMs?.toFixed(2) ?? "—"} мс · Smart Turn: {value.smartTurnMs?.toFixed(1) ?? "—"} мс · Разбор команды: {value.interpretationMs?.toFixed(1) ?? "—"} мс · Получение LLM-ответа: {value.llmMs?.toFixed(1) ?? "—"} мс · Последний синтез TTS: {value.ttsMs?.toFixed(1) ?? "—"} мс</p>
    {value.firstOutputMs !== undefined && <p>Первый фрагмент модели: {value.firstOutputMs.toFixed(1)} мс от начала вызова</p>}
    </>}
    <ol aria-label="События голосового диалога">{events.slice(-40).map((event) => <li key={event.sequence} data-voice-event={event.name} data-voice-role={event.role} data-voice-request={event.requestId}>
      {event.atMs} мс · {eventLabels[event.name]}{event.utterance ? ` · реплика ${event.utterance}` : ""}{event.reason ? " · " + (reasonLabels[event.reason] || event.reason) : ""}
      {event.durationMs !== undefined ? ` · аудио ${Math.round(event.durationMs)} мс` : ""}{event.characters !== undefined ? ` · символов ${event.characters}` : ""}{event.queueFrames !== undefined ? ` · в очереди ${event.queueFrames}` : ""}{event.milliseconds !== undefined ? ` · обработка ${event.milliseconds.toFixed(1)} мс` : ""}
      {event.oldestMs !== undefined ? ` · ожидание старейшего кадра ${Math.round(event.oldestMs)} мс` : ""}
    </li>)}</ol>
  </details>;
}
