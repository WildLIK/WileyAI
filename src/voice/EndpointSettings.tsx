import { useEffect, useState } from "react";
import { request, type Settings } from "../api";
import { SettingsSwitch } from "../SettingsSwitch";

type Status = { installed: boolean; available: boolean; model: string; size: number };
export function EndpointSettings({ settings, onChange }: { settings: Settings; onChange(value: Settings): void }) {
  const [status, setStatus] = useState<Status>();
  const [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const load = () => request<Status>("/voice/endpoint/status").then(setStatus).catch(() => setMessage("Статус Smart Turn недоступен; VAD продолжает работать самостоятельно."));
  useEffect(() => { void load(); }, []);
  return <div className="card" aria-label="Завершение голосовой реплики">
    <h2>Когда отвечать</h2>
    <label>Режим диалога<select aria-label="Режим окончания речи" value={settings.conversation_endpoint_mode} onChange={(event) => onChange({ ...settings, conversation_endpoint_mode: event.target.value as Settings["conversation_endpoint_mode"] })}>
      <option value="auto">Автоматически — рекомендуется</option><option value="commands">Быстрые команды</option><option value="conversation">Обычный разговор</option><option value="dictation">Диктовка</option>
    </select></label>
    <p className="help">Быстрые команды ждут короткую паузу. Обычный разговор и диктовка допускают больше времени между словами. Непрерывная речь сохраняется до установленного предела реплики.</p>
    <SettingsSwitch label="Проверять завершённость фразы через Smart Turn" description={settings.conversation_vad === "rms" ? "Сохранённый выбор применяется с Silero. При ручном RMS эта проверка не используется; сам переключатель не скачивает модель." : "Необязательная локальная проверка на паузе. При недоступной модели конец реплики определяет VAD. Включение не скачивает веса."} checked={settings.conversation_smart_turn} disabled={busy} onChange={(value) => onChange({ ...settings, conversation_smart_turn: value })} />
    <p className="help">Необязательная локальная модель, около 8,3 МиБ. Работает с Silero VAD и вызывается на паузе. Если модель отсутствует или отвечает медленно, используется VAD с ограничением ожидания. Аудио не отправляется во внешнюю сеть.</p>
    {status && <p className="help">{status.model}: {status.installed ? "веса установлены" : "веса не установлены"}; {status.available ? "движок доступен" : "движок не установлен — установите компонент Smart Turn CPU в разделе «Модели» и перезапустите WileyAI"}.</p>}
    {!status?.installed && <button className="outline" disabled={busy} onClick={() => {
      setBusy(true); setMessage("Загружаю веса Smart Turn — около 8,3 МиБ. Настройка сама не включается.");
      void request("/voice/endpoint/install", "POST").then(load).then(() => setMessage("Веса Smart Turn установлены.")).catch((error) => setMessage(String(error))).finally(() => setBusy(false));
    }}>{busy ? "Загрузка Smart Turn…" : "Скачать веса Smart Turn · 8,3 МиБ"}</button>}
    <details><summary>Дополнительно: детектор речи</summary><label>Движок VAD<select aria-label="Движок VAD" value={settings.conversation_vad} onChange={(event) => onChange({ ...settings, conversation_vad: event.target.value as Settings["conversation_vad"] })}>
      <option value="auto">Автоматически — локальный Silero, RMS при ошибке</option><option value="silero">Silero VAD локально</option><option value="rms">RMS — резервный порог громкости</option>
    </select></label><p className="help">Silero VAD поставляется с WileyAI. RMS хуже различает музыку и речь. Длина паузы настраивается ниже и используется как основа выбранного режима.</p></details>
    {message && <p role="status">{message}</p>}
  </div>;
}
