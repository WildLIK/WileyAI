import { useEffect, useState } from "react";
import { request, scoped, type Settings } from "./api";

type Status = {
  enabled: boolean;
  model: string;
  ready: number;
  total: number;
  complete: boolean;
  job: { state: string; completed: number; total: number; text: string };
};

export function SemanticSearch({
  settings,
  conversationId,
  onSave,
  onError,
}: {
  settings: Settings;
  conversationId: string;
  onSave: (value: Settings) => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [draft, setDraft] = useState(settings);
  const [status, setStatus] = useState<Status>();
  const [busy, setBusy] = useState(false);
  useEffect(() => setDraft(settings), [settings]);
  useEffect(() => {
    let disposed = false;
    const load = () =>
      request<Status>(scoped("/semantic", conversationId))
        .then((value) => {
          if (!disposed) setStatus(value);
        })
        .catch((error) => {
          if (!disposed) onError(error);
        });
    void load();
    const timer = setInterval(() => void load(), 2500);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [conversationId, onError]);
  async function action(route: string, method = "POST") {
    setBusy(true);
    try {
      await onSave(draft);
      await request(scoped(route, conversationId), method);
      setStatus(await request<Status>(scoped("/semantic", conversationId)));
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card">
      <h2>Семантический поиск</h2>
      <p>
        Поиск памяти и документов по смыслу. Отдельная локальная модель
        embeddings; модель общения не заменяется.
      </p>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={draft.embedding_enabled}
          onChange={(event) =>
            setDraft({ ...draft, embedding_enabled: event.target.checked })
          }
        />
        Использовать локальный поиск по смыслу
      </label>
      <label>
        Локальный сервер embeddings
        <input
          value={draft.embedding_base_url}
          onChange={(event) =>
            setDraft({ ...draft, embedding_base_url: event.target.value })
          }
        />
      </label>
      <label>
        Модель embeddings
        <input
          value={draft.embedding_model}
          maxLength={200}
          placeholder="embeddinggemma:300m"
          onChange={(event) =>
            setDraft({ ...draft, embedding_model: event.target.value })
          }
        />
      </label>
      <p className="help">
        EmbeddingGemma 300M: около 622 МБ, многоязычный поиск. Нужен
        установленный Ollama. Текст передаётся только локальному движку.
        Облачные embeddings не используются.
      </p>
      <div className="button-row">
        <button
          disabled={busy}
          onClick={() => void action("/semantic/download")}
        >
          Сохранить и скачать модель
        </button>
        <button
          disabled={
            busy || !draft.embedding_enabled || status?.job.state === "running"
          }
          onClick={() => void action("/semantic/rebuild")}
        >
          Обновить индекс этого пространства
        </button>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onSave(draft);
            } catch (error) {
              onError(error);
            } finally {
              setBusy(false);
            }
          }}
        >
          Сохранить поиск
        </button>
        {status?.job.state === "running" && (
          <button onClick={() => void action("/semantic/rebuild", "DELETE")}>
            Остановить индексирование
          </button>
        )}
      </div>
      {status && (
        <>
          <p role="status">
            {status.job.text}. Готово фрагментов: {status.ready} из{" "}
            {status.total}.
          </p>
          {status.job.state === "running" && (
            <progress
              value={status.job.completed}
              max={Math.max(1, status.job.total)}
            />
          )}
        </>
      )}
      <p className="help">
        После добавления/изменения файлов и памяти обновите индекс. Смена модели
        или её весов требует перестройки. Если индекса или модели нет,
        сохраняется обычный поиск по словам. Проекты и документы чужих чатов в
        результаты не попадают; оригинал доступен из карточки. Кеш векторов
        можно удалить без потери документов.
      </p>
    </div>
  );
}
