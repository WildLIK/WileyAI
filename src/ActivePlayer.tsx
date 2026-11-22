import { useEffect, useState } from "react";
import { request } from "./api";

type Session = { id: string; player: string; state: string; backend: string; current?: boolean; commands: string[]; track?: { title: string; artist: string } };
type Inventory = { selected: string; sessions: Session[]; warnings: string[]; auto_connect: boolean; auto_play: boolean; special: { connected: boolean; error?: string } };
export function ActivePlayer({ onChanged }: { onChanged(): Promise<void> }) {
  const [state, setState] = useState<Inventory>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async () => { setBusy(true); try { setState(await request<Inventory>("/media")); setError(""); } catch (reason) { setError(String(reason)); } finally { setBusy(false); } };
  useEffect(() => { void load(); }, []);
  const save = async (source: string, auto: boolean, autoPlay = state?.auto_play ?? false) => {
    const previous = state;
    setState((current) => current && { ...current, selected: source, auto_connect: auto, auto_play: autoPlay });
    setBusy(true);
    try { await request("/media/preferences", "PUT", { source, auto_connect: auto, auto_play: autoPlay }); await onChanged(); await load(); }
    catch (reason) { setState(previous); setError(String(reason)); } finally { setBusy(false); }
  };
  const labels: Record<string, string> = { play: "Продолжить", pause: "Пауза", next: "Следующий", previous: "Предыдущий", stop: "Стоп", play_pause: "Воспроизведение / пауза" };
  const states: Record<string, string> = { Playing: "Воспроизведение", Paused: "Пауза", Stopped: "Остановлено", Closed: "Закрыто", Opened: "Открыто", Changing: "Переход" };
  return <section className="card" aria-label="Активный проигрыватель">
    <div className="button-row"><h2>Активный проигрыватель</h2><button disabled={busy} onClick={() => void load()}>Обновить плееры</button></div>
    <p className="help">«Убавь звук» меняет громкость Windows. «Сделай музыку потише» относится к приложению. При нескольких подходящих плеерах Уайли уточнит выбор.</p>
    {state && <><label>Источник<select aria-label="Источник музыки" disabled={busy} value={state.selected} onChange={(event) => void save(event.target.value, state.auto_connect)}><option value="auto">Автоматически</option>
      {state.selected !== "auto" && !state.sessions.some((row) => row.id === state.selected) && <option value={state.selected}>Выбранный плеер недоступен</option>}
      {state.sessions.filter((row, index, all) => all.findIndex((other) => other.id === row.id) === index).map((row) => <option key={row.id} value={row.id}>{row.player}</option>)}
    </select></label>
    {!state.sessions.length && <p>Доступные медиасессии не найдены. Откройте плеер и выберите композицию.</p>}
    {state.sessions.map((row, index) => <div key={row.id + index}><strong>{row.player}</strong> — {states[row.state] || row.state}{row.current ? " · текущая сессия Windows" : ""}<p className="help">{row.track?.artist} {row.track?.title} · Доступно: {row.commands.map((command) => labels[command] || command).join(", ") || "нет команд"}</p></div>)}
    <p className="help">Специальная интеграция Яндекс Музыки: {state.special.connected ? "подключена" : state.special.error || "не подключена"}. Команды выбранной Яндекс Музыки используют это подключение; другие плееры — системные медиасессии.</p>
    <label className="checkbox"><input type="checkbox" checked={state.auto_connect} disabled={busy} onChange={(event) => void save(state.selected, event.target.checked)} /> Автоматически подключать Яндекс Музыку при запуске через WileyAI</label>
    <p className="help">Перезапуск уже открытого плеера требует отдельного согласия и прервёт воспроизведение.</p>
    <label className="checkbox"><input type="checkbox" checked={state.auto_play ?? false} disabled={busy} onChange={(event) => void save(state.selected, state.auto_connect, event.target.checked)} /> Запускать «Мою волну» после открытия Яндекс Музыки (использует специальное подключение)</label>
    <p className="help">При включённой настройке WileyAI подключит плеер и запустит «Мою волну» после открытия через WileyAI. Запуск подтверждается состоянием трека и движением позиции. Если кнопка недоступна, повторного нажатия не будет.</p>
    {state.warnings.map((warning) => <p className="help" key={warning}>{warning}</p>)}</>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
