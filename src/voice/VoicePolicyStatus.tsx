import { activationPolicy, policyReasons, sessionPolicy, type VoicePolicyConfig, type VoiceSessionPolicy } from "./policy";
const environment = (value?: VoicePolicyConfig) => value ? value.stt_environment === "music" ? "Музыка и шум" : "Обычная комната" : "ещё не загружено";

export function VoicePolicyStatus({ saved, session, active, speaking, dirty, saving, saveFailed = false }: {
  saved?: VoicePolicyConfig; session: VoiceSessionPolicy | null; active: boolean; speaking: boolean; dirty: boolean; saving: boolean; saveFailed?: boolean;
}) {
  const policy = session && activationPolicy(session, active && speaking && session.conversation_barge_in ? "barge" : "main");
  const effectiveQueue = session?.conversation_listen_while_thinking ? session.conversation_queue_mode ?? "sequential" : "sequential";
  return <section className="voice-policy-status" aria-label="Действующий режим разговора">
    <p data-voice-policy="saved">Сохранённый профиль: <strong>{environment(saved)}</strong>.</p>
    <p data-voice-policy="saving">{saving ? "Сохраняю настройки…" : saveFailed ? "Не удалось сохранить изменения. Сохранённые настройки остались прежними." : dirty ? "Есть несохранённые изменения. Сеанс использует сохранённые настройки." : "Изменения сохранены."}</p>
    {session ? <>
      <p data-voice-policy="effective">{active ? "Текущий сеанс" : "Последний сеанс"}: <strong>{environment(session)}</strong> · {session.stt_model}. Запущен кнопкой.</p>
      <p>Во время выполнения: {{sequential: "последовательно, без очереди",latest: "сохранять последнюю фразу",queue: "очередь до трёх фраз"}[effectiveQueue]}.</p>
      <p data-voice-policy="activation">{policy?.required ? "Имя требуется" : "Имя не требуется"}: {policy && policyReasons[policy.reason]}. {session.conversation_barge_in && "Во время озвучки для перебивания нужно имя."}</p>
    </> : <p>Разговор ещё не запущен. Кнопка начинает сеанс с сохранёнными настройками.</p>}
    {active && dirty && <p>Чтобы применить изменения, завершите разговор, сохраните настройки и начните новый сеанс.</p>}
    {active && saved && session && JSON.stringify(sessionPolicy(saved)) !== JSON.stringify(session) && <p>Сохранённые настройки отличаются от текущего сеанса. Они применятся при следующем запуске разговора.</p>}
    <p>Фоновое пробуждение по имени: не поддерживается. Микрофон вне запущенного разговора не слушает имя.</p>
  </section>;
}
