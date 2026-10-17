import { useState } from "react";
import { request, scoped, type Message, type Settings } from "./api";

export function SearchSources({
  message,
  onError,
  onNotice,
}: {
  message: Message;
  onError: (error: unknown) => void;
  onNotice: (text: string) => void;
}) {
  const search = message.web_search;
  const [opening, setOpening] = useState(false);
  if (!search) return null;
  async function open(index: number) {
    setOpening(true);
    try {
      const result = await request<{ text: string }>(
        message.conversation_id
          ? scoped("/web/open-source", message.conversation_id)
          : "/web/open-source",
        "POST",
        { message_id: message.id, index },
      );
      onNotice(result.text);
    } catch (error) {
      onError(error);
    } finally {
      setOpening(false);
    }
  }
  return (
    <section className="search-sources" aria-label="Источники веб-поиска">
      <strong>Источники · {search.results.length}</strong>
      <p className="help">
        {search.provider === "brave" ? "Brave Search" : "SearXNG"} ·{" "}
        {new Date(search.checked_at).toLocaleString("ru-RU")} · {search.query}
      </p>
      <p className="help">Поисковые выдержки. Полные страницы не прочитаны.</p>
      {search.partial && (
        <p className="search-warning">
          Часть поисковых движков не ответила. Результаты могут быть неполными.
        </p>
      )}
      <ol>
        {search.results.map((item, index) => (
          <li key={item.url}>
            <button
              className="source-link"
              disabled={opening}
              aria-label={"Открыть источник " + (index + 1) + ": " + item.title}
              onClick={() => void open(index)}
            >
              {item.title}
            </button>
            <small className="source-address">{item.url}</small>
            <p>{item.snippet}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function SearchSettings({
  settings,
  onChange,
  secret,
  onSecret,
}: {
  settings: Settings;
  onChange: (value: Settings) => void;
  secret: string;
  onSecret: (value: string) => void;
}) {
  return (
    <div className="card">
      <h2>Поиск в интернете</h2>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.search_enabled}
          onChange={(event) =>
            onChange({ ...settings, search_enabled: event.target.checked })
          }
        />
        Разрешить веб-поиск по моей команде
      </label>
      <details className="settings-help">
        <summary>Как работает поиск и какие данные отправляются</summary>
        <p className="help">
          Запуск: кнопка «Поиск» в чате или «Найди в интернете…», в том числе
          голосом. Сервис получает только текст поискового запроса. История,
          память и документы автоматически к нему не добавляются. Найденные
          выдержки передаются выбранной модели для ответа.
        </p>
      </details>
      <label>
        Поисковый сервис
        <select
          value={settings.search_provider}
          onChange={(event) =>
            onChange({
              ...settings,
              search_provider: event.target
                .value as Settings["search_provider"],
            })
          }
        >
          <option value="searxng">SearXNG · свой сервер</option>
          <option value="brave">Brave Search · отдельный ключ API</option>
        </select>
      </label>
      {settings.search_provider === "searxng" ? (
        <>
          <label>
            Адрес SearXNG
            <input
              value={settings.search_base_url}
              onChange={(event) =>
                onChange({ ...settings, search_base_url: event.target.value })
              }
              placeholder="http://127.0.0.1:8080"
            />
          </label>
          <p className="help">
            Укажите базовый адрес сервера с включённым JSON API. Локальный
            SearXNG обращается к внешним поисковым системам; работа полностью
            без сети здесь невозможна.
          </p>
        </>
      ) : (
        <>
          <label>
            Ключ Brave Search
            <input
              type="password"
              autoComplete="off"
              value={secret}
              onChange={(event) => onSecret(event.target.value)}
              placeholder={
                settings.has_search_api_key
                  ? "Ключ поиска сохранён в Windows"
                  : "Ключ из аккаунта Brave Search API"
              }
            />
          </label>
          <button className="subtle" onClick={() => onSecret("")}>
            Удалить ключ поиска при сохранении
          </button>
          <p className="help">
            Используется отдельный ключ поиска. Доступность, лимиты и стоимость
            зависят от вашего аккаунта Brave.
          </p>
        </>
      )}
      <label>
        Фильтр результатов
        <select
          value={settings.search_filter}
          onChange={(event) =>
            onChange({
              ...settings,
              search_filter: event.target.value as Settings["search_filter"],
            })
          }
        >
          <option value="off">Без фильтра</option>
          <option value="moderate">Умеренный</option>
          <option value="strict">Строгий</option>
        </select>
      </label>
      <p className="help">
        Нажмите «Сохранить» вверху настроек. Автоматического поиска в фоне нет.
        Результаты — поисковые выдержки со ссылками, их качество зависит от
        сервиса.
      </p>
    </div>
  );
}
