import { useState } from "react";
import type { BackupPreview } from "./api";

const labels: [string, string][] = [
  ["projects", "Проекты"],
  ["conversations", "Чаты"],
  ["messages", "Сообщения"],
  ["memories", "Записи памяти"],
  ["notes", "Заметки"],
  ["tasks", "Задачи и напоминания"],
  ["calendar_events", "События календаря"],
  ["calendar_alerts", "Уведомления календаря"],
  ["routines", "Сценарии запуска"],
  ["documents", "Документы чатов"],
  ["project_documents", "Документы проектов"],
  ["aliases", "Команды открытия — по выбору"],
];

export function BackupPanel({
  disabled,
  onError,
  onNotice,
}: {
  disabled: boolean;
  onError: (error: unknown) => void;
  onNotice: (message: string) => void;
}) {
  const [working, setWorking] = useState(false);
  const [preview, setPreview] = useState<BackupPreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [connections, setConnections] = useState(false);
  const [aliases, setAliases] = useState(false);
  const [saved, setSaved] = useState("");
  const [recovery, setRecovery] = useState("");
  async function exportData() {
    setWorking(true);
    try {
      const result = await window.wiley.exportBackup();
      if (result) {
        setSaved(result.path);
        onNotice("Резервная копия сохранена");
      }
    } catch (error) {
      onError(error);
    } finally {
      setWorking(false);
    }
  }
  async function choose() {
    setWorking(true);
    setPreview(null);
    setConfirmed(false);
    setConnections(false);
    setAliases(false);
    try {
      setPreview(await window.wiley.previewBackup());
    } catch (error) {
      onError(error);
    } finally {
      setWorking(false);
    }
  }
  async function restore() {
    if (!preview || !confirmed) return;
    setWorking(true);
    try {
      const result = await window.wiley.restoreBackup({
        ticket: preview.ticket,
        connections,
        aliases,
      });
      setRecovery(result.recovery_path);
      setPreview(null);
      setSaved("");
      onNotice("Данные восстановлены. Защитная копия сохранена");
    } catch (error) {
      setPreview(null);
      onError(error);
    } finally {
      setWorking(false);
    }
  }
  return (
    <div className="card backup-card" aria-label="Резервные копии">
      <h2>Резервные копии и перенос</h2>
      <p>
        Сохраните переписку, память, личность, заметки, задачи и текст
        документов в один файл.
      </p>
      <p className="help">
        Копия содержит личные данные и не зашифрована. Ключи из хранилища
        Windows, веса моделей, сам VRM и исходные файлы документов в неё не
        входят. В копию входят только сохранённые настройки.
      </p>
      <div className="button-row">
        <button
          className="outline"
          disabled={disabled || working}
          onClick={() => void exportData()}
        >
          {working ? "Обрабатываю…" : "Сохранить резервную копию"}
        </button>
        <button
          className="outline"
          disabled={disabled || working}
          onClick={() => void choose()}
        >
          Выбрать копию для восстановления
        </button>
      </div>
      {saved && <p className="file-path">Копия сохранена: {saved}</p>}
      {disabled && (
        <p className="help">
          Завершите разговор, запись и воспроизведение перед работой с копиями.
        </p>
      )}
      {preview && (
        <div className="backup-preview">
          <h3>Проверка перед восстановлением</h3>
          <p>
            {preview.filename} ·{" "}
            {new Date(preview.created).toLocaleString("ru-RU")}
          </p>
          <p>
            Личность из копии: <strong>{preview.name}</strong>
          </p>
          <table>
            <thead>
              <tr>
                <th>Данные</th>
                <th>Сейчас</th>
                <th>В копии</th>
              </tr>
            </thead>
            <tbody>
              {labels.map(([key, label]) => (
                <tr key={key}>
                  <td>{label}</td>
                  <td>{preview.current_counts[key]}</td>
                  <td>{preview.counts[key]}</td>
                </tr>
              ))}
              <tr>
                <td>Ожидающие предложения памяти</td>
                <td>{preview.current_pending_suggestions}</td>
                <td>{preview.pending_suggestions}</td>
              </tr>
            </tbody>
          </table>
          <p>
            Переписка, память, заметки, задачи и документы будут заменены
            данными из копии. Просроченные напоминания могут сработать сразу.
            Перед заменой WileyAI сохранит защитную копию текущих данных.
            Несохранённые черновики во всех окнах сбросятся.
          </p>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={connections}
              disabled={working}
              onChange={(event) => setConnections(event.target.checked)}
            />
            Также восстановить подключение, модели, голос, устройства и путь к
            аватару
          </label>
          {connections && (
            <p className="help">
              Подключение из копии: {preview.provider} · {preview.model} ·{" "}
              {preview.base_url}. Ключ нужно настроить в Windows отдельно. Файлы
              и устройства на другом ПК могут отличаться. Веб-поиск после
              импорта подключений будет выключен; разрешите его заново после
              проверки настроек.
            </p>
          )}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={aliases}
              disabled={working}
              onChange={(event) => setAliases(event.target.checked)}
            />
            Также заменить команды открытия командами из копии
          </label>
          <p className="help">
            Без этих опций текущее подключение, модели, устройства, пути и
            команды сохранятся. Имя, характер и настройка предложений памяти
            восстановятся из копии. Команды при импорте не запускаются.
          </p>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={working}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            Подтверждаю замену текущих данных копией
          </label>
          <div className="button-row">
            <button
              className="primary"
              disabled={disabled || working || !confirmed}
              onClick={() => void restore()}
            >
              Восстановить данные
            </button>
            <button
              className="subtle"
              disabled={working}
              onClick={() => setPreview(null)}
            >
              Отмена восстановления
            </button>
          </div>
        </div>
      )}
      {recovery && (
        <p className="file-path">
          Защитная копия перед восстановлением: {recovery}
        </p>
      )}
    </div>
  );
}
