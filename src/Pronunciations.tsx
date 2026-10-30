import { useEffect, useState } from "react";
import { request } from "./api";

type App = { id: string; name: string; source: string; aliases?: string[] };
type Rule = { id: string; application_id: string; application_name: string; spoken: string; enabled: boolean };
type Preview = { text: string; intent: string | null; target?: string; match: string; candidates: string[]; requires_confirmation?: boolean; elapsed_ms: number };

export function Pronunciations({ onError, heard = "" }: { onError(error: unknown): void; heard?: string }) {
  const [apps, setApps] = useState<App[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [app, setApp] = useState("");
  const [spoken, setSpoken] = useState("");
  const [editing, setEditing] = useState("");
  const [test, setTest] = useState(heard);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    const [found, saved] = await Promise.all([request<{ items: App[] }>("/applications"), request<Rule[]>("/voice/pronunciations")]);
    setApps(found.items); setRules(saved);
  };
  useEffect(() => { void refresh().catch(onError); }, []);
  const save = async () => {
    setBusy(true);
    try {
      await request(editing ? `/voice/pronunciations/${editing}` : "/voice/pronunciations", editing ? "PUT" : "POST", { application_id: app, spoken, enabled: true });
      setSpoken(""); setEditing(""); await refresh();
    } catch (error) { onError(error); } finally { setBusy(false); }
  };
  const remove = async (id: string) => {
    try { await request(`/voice/pronunciations/${id}`, "DELETE"); await refresh(); } catch (error) { onError(error); }
  };
  const toggle = async (rule: Rule) => {
    const selected = apps.find((item) => item.name === rule.application_name);
    if (!selected) return onError(new Error("Сначала найдите приложение повторным сканированием."));
    try { await request(`/voice/pronunciations/${rule.id}`, "PUT", { application_id: selected.id, spoken: rule.spoken, enabled: !rule.enabled }); await refresh(); } catch (error) { onError(error); }
  };
  return <div className="card">
    <h2>Мои произношения</h2>
    <p className="help">Добавьте исправление только после проверки. Сходные варианты предлагаются для выбора и не запускаются автоматически. Аудиозаписи не сохраняются.</p>
    <button type="button" disabled={busy} onClick={() => { setBusy(true); void request<{ items: App[] }>("/applications/scan", "POST").then((value) => setApps(value.items)).catch(onError).finally(() => setBusy(false)); }}>Найти приложения</button>
    <label>Приложение<select aria-label="Приложение для произношения" value={app} onChange={(event) => setApp(event.target.value)}><option value="">Выберите приложение</option>{apps.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.source}</option>)}</select></label>
    {app && <p className="help">Автоматически из каталога: {Array.from(new Set([apps.find((item) => item.id === app)?.name, ...(apps.find((item) => item.id === app)?.aliases || [])].filter(Boolean))).join(", ")}.</p>}
    <label>Как вы его называете<input aria-label="Произношение приложения" value={spoken} onChange={(event) => setSpoken(event.target.value)} maxLength={100} placeholder="Например, ОПС" /></label>
    <button type="button" disabled={!app || !spoken.trim() || busy} onClick={() => void save()}>{editing ? "Сохранить исправление" : "Запомнить произношение"}</button>
    {editing && <button type="button" onClick={() => { setEditing(""); setSpoken(""); }}>Отмена</button>}
    {rules.map((rule) => <div key={rule.id}><span>{rule.application_name} — «{rule.spoken}» · подтверждено пользователем{rule.enabled ? "" : " · отключено"}</span>{" "}
      <button type="button" onClick={() => { const selected = apps.find((item) => item.name === rule.application_name); if (!selected) return onError(new Error("Приложение не найдено; выполните сканирование.")); setApp(selected.id); setSpoken(rule.spoken); setEditing(rule.id); }}>Изменить</button>{" "}
      <button type="button" onClick={() => void toggle(rule)}>{rule.enabled ? "Отключить" : "Включить"}</button>{" "}
      <button type="button" onClick={() => void remove(rule.id)}>Удалить</button></div>)}
    <label>Проверка без запуска<input aria-label="Фраза для проверки распознавания" value={test} onChange={(event) => setTest(event.target.value)} placeholder="Открой ОПС" /></label>
    <button type="button" disabled={!test.trim()} onClick={() => { void request<Preview>("/voice/pronunciations/preview", "POST", { text: test }).then(setPreview).catch(onError); }}>Проверить фразу</button>
    {preview && <p role="status">Уайли услышала: «{preview.text}». {preview.match}{preview.candidates.length ? `: ${preview.candidates.join(", ")}` : ""}. {preview.requires_confirmation ? "Потребуется подтверждение. " : ""}Проверка: {preview.elapsed_ms} мс. Ничего не запущено.</p>}
  </div>;
}
