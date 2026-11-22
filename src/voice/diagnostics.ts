/** Metadata only: transcripts, audio, credentials and arbitrary errors are never retained. */
export type VoiceEventName =
  | "vad_ready" | "vad_initialization_failed" | "vad_timeout" | "vad_fallback_rms"
  | "speech_started" | "pause_detected" | "utterance_finalized" | "utterance_rejected"
  | "smart_turn_started" | "smart_turn_completed" | "smart_turn_failed" | "smart_turn_timeout" | "smart_turn_cancelled"
  | "stt_started" | "stt_completed" | "stt_empty" | "stt_failed" | "stt_rejected"
  | "activation_accepted" | "activation_rejected" | "request_dispatched" | "request_cancelled"
  | "request_failed" | "response_started" | "turn_recovered" | "session_stopped" | "tts_failed"
  | "tts_requested" | "tts_playing";
export type VoiceEventDetails = {
  reason?: string; engine?: string; profile?: string; role?: string;
  utterance?: number; durationMs?: number; voicedMs?: number; milliseconds?: number;
  characters?: number; queueFrames?: number; oldestMs?: number; required?: boolean;
  requestId?: string;
};
export type VoiceEvent = VoiceEventDetails & { name: VoiceEventName; sequence: number; atMs: number };
export type VoiceEventSink = (name: VoiceEventName, details?: VoiceEventDetails) => void;

export class VoiceTrace {
  private values: VoiceEvent[] = [];
  private began = performance.now();
  private sequence = 0;
  get events() { return this.values.map((value) => ({ ...value })); }
  add(name: VoiceEventName, details: VoiceEventDetails = {}) {
    const safe: Record<string, string | number | boolean> = {};
    for (const key of ["reason", "engine", "profile", "role"] as const) {
      const value = details[key];
      if (typeof value === "string" && /^[a-z0-9_.-]{1,80}$/i.test(value)) safe[key] = value;
    }
    for (const key of ["utterance", "durationMs", "voicedMs", "milliseconds", "characters", "queueFrames", "oldestMs"] as const) {
      const value = details[key];
      if (typeof value === "number" && Number.isFinite(value) && value >= 0 && value < 1e9) safe[key] = Math.round(value * 100) / 100;
    }
    if (typeof details.required === "boolean") safe.required = details.required;
    if (typeof details.requestId === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(details.requestId)) {
      safe.requestId = details.requestId;
    }
    const event: VoiceEvent = { ...safe, name, sequence: ++this.sequence, atMs: Math.round(performance.now() - this.began) };
    this.values.push(event); if (this.values.length > 80) this.values.shift();
    return { ...event };
  }
}

export const eventLabels: Record<VoiceEventName, string> = {
  turn_recovered: "Ошибка реплики обработана; разговор продолжается", session_stopped: "Сеанс завершён", tts_failed: "Озвучка недоступна",
  tts_requested: "Запрос синтеза отправлен", tts_playing: "Началось воспроизведение",
  vad_ready: "Silero готов", vad_initialization_failed: "VAD не подготовлен", vad_timeout: "Превышен дедлайн VAD", vad_fallback_rms: "Включён резервный RMS",
  speech_started: "Начало речи", pause_detected: "Обнаружена пауза", utterance_finalized: "Запись завершена", utterance_rejected: "Сегмент отклонён до STT",
  smart_turn_started: "Проверка Smart Turn", smart_turn_completed: "Результат Smart Turn", smart_turn_failed: "Ошибка Smart Turn", smart_turn_timeout: "Дедлайн Smart Turn", smart_turn_cancelled: "Проверка Smart Turn отменена",
  stt_started: "Запрос STT отправлен", stt_completed: "STT ответил", stt_empty: "STT вернул пустой текст", stt_failed: "Ошибка STT",
  stt_rejected: "Результат STT отклонён",
  activation_accepted: "Обращение принято", activation_rejected: "Обращение отклонено", request_dispatched: "Запрос передан в чат", request_cancelled: "Запрос отменён", request_failed: "Ответ не получен", response_started: "Начало ответа",
};
export const reasonLabels: Record<string, string> = {
  turn_error: "Ошибка текущей реплики; повтор не отправлялся", capture_error: "Ошибка устройства захвата", preparation_failed: "Не удалось подготовить сеанс", tts_rate_limited: "Лимит озвучки; временно только текст", tts_error: "Ошибка озвучки; текст сохранён",
  duplicate_queued: "Повтор текущей реплики в очереди", queued_expired: "Отложенная реплика устарела",
  stt_repetitive_transcript: "Повторяющийся текст не соответствует длительности записи", stt_prompt_echo: "Распознавание повторило подсказку словаря",
  stt_implausible_transcript: "Слишком много текста для этой длительности аудио", stt_phantom: "Известный ложный результат на шуме", stt_no_signal: "В записи только цифровая тишина",
  worker_timeout: "Worker не вернул результат за 500 мс", queue_overflow: "Переполнен ограниченный буфер PCM",
  worker_error: "Worker остановился с ошибкой", inference_failed: "Ошибка вычисления модели", invalid_score: "Некорректная оценка модели",
  initialization_failed: "Ошибка загрузки модели или runtime", initialization_timeout: "Подготовка модели не завершилась", unsupported_sample_rate: "Частота захвата отличается от 16 кГц",
  too_short: "Недостаточно подтверждённой речи", empty: "Пустой транскрипт", name_missing: "Нет обращения по имени в начале", missing_wake_name: "Нет обращения по имени в начале", music_name_missing: "Музыкальный профиль требует имя в начале фразы",
  name_only: "Распознано только имя, без просьбы", not_required: "Повторное имя не требуется", addressed: "Имя распознано в начале", caller_verified: "Проверено обработчиком",
  playback_echo: "Распознано собственное воспроизведение", stt_timeout: "Истёк дедлайн распознавания", stt_error: "Ошибка распознавателя", server_unavailable: "Нет связи с сервером",
  user_cancelled: "Остановлено пользователем", session_stale: "Сеанс устарел", capture_stalled: "Прекратились PCM-кадры", complete: "Фраза завершена", incomplete: "Фразе требуется продолжение", unavailable: "Модель недоступна",
  speech_resumed: "Пользователь продолжил говорить", segment_reset: "Сегмент завершён или сброшен", pause: "Пауза", silence_limit: "Предел ожидания после паузы", maximum: "Максимальная длина записи", smart_complete: "Smart Turn подтвердил окончание",
};
