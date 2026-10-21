import { useEffect, useRef, useState } from "react";
import { request, type Settings } from "./api";

type Forecast = {
  place: string;
  timezone: string;
  checked_at: string;
  current: {
    temperature: number;
    feels_like: number;
    wind: number;
    condition: string;
    time: string;
  } | null;
  days: {
    date: string;
    low: number;
    high: number;
    rain: number;
    condition: string;
  }[];
  sources: { title: string; url: string }[];
};
const periods = [
  { label: "Сейчас и сегодня", day: 0, days: 1 },
  { label: "Завтра", day: 1, days: 1 },
  { label: "Послезавтра", day: 2, days: 1 },
  { label: "На неделю", day: 0, days: 7 },
];
const temperature = (value: number) =>
  `${value > 0 ? "+" : ""}${value.toLocaleString("ru-RU")}°`;

export function WeatherSettings({
  settings,
  onChange,
}: {
  settings: Settings;
  onChange: (value: Settings) => void;
}) {
  const [city, setCity] = useState("");
  const [period, setPeriod] = useState(0),
    [forecast, setForecast] = useState<Forecast | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const active = useRef<AbortController | null>(null),
    version = useRef(0);
  function clear() {
    version.current++;
    active.current?.abort();
    active.current = null;
    setBusy(false);
    setError("");
    setForecast(null);
  }
  useEffect(() => {
    clear();
  }, [settings.weather_city, settings.web_dns]);
  useEffect(
    () => () => {
      version.current++;
      active.current?.abort();
    },
    [],
  );
  async function load() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    const generation = ++version.current;
    setBusy(true);
    setError("");
    setForecast(null);
    try {
      const value = await request<Forecast>(
        "/weather/preview",
        "POST",
        {
          city: city.trim() || settings.weather_city.trim(),
          day: periods[period].day,
          days: periods[period].days,
          dns_mode: settings.web_dns,
        },
        controller.signal,
      );
      if (!controller.signal.aborted && generation === version.current)
        setForecast(value);
    } catch (err) {
      if (!controller.signal.aborted && generation === version.current)
        setError(String(err));
    } finally {
      if (generation === version.current) {
        active.current = null;
        setBusy(false);
      }
    }
  }
  return (
    <section className="weather-settings" aria-label="Погода">
      <h3>Погода</h3>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.weather_enabled}
          onChange={(event) =>
            onChange({ ...settings, weather_enabled: event.target.checked })
          }
        />
        Получать погоду через Open-Meteo
      </label>
      <label>
        Город для погоды
        <input
          value={settings.weather_city}
          maxLength={100}
          placeholder="Москва, Россия"
          onChange={(event) => {
            clear();
            onChange({ ...settings, weather_city: event.target.value });
          }}
        />
      </label>
      <p className="help">
        Для запросов в чате сохраните город и разрешение общей кнопкой
        «Сохранить». Можно сказать «Какая сейчас погода?», «Погода завтра в
        Москве» или «Прогноз на неделю». Модель и поисковый сервер не нужны. В
        верхней панели погода сохранённого города обновляется раз в 30 минут.
      </p>
      <div className="weather-preview-tools">
        <label>
          Другой город для проверки
          <input
            value={city}
            maxLength={100}
            placeholder="Необязательно: Москва, Россия"
            onChange={(event) => {
              clear();
              setCity(event.target.value);
            }}
          />
        </label>
        <label>
          Период прогноза
          <select
            aria-label="Период прогноза"
            value={period}
            onChange={(event) => {
              clear();
              setPeriod(Number(event.target.value));
            }}
          >
            {periods.map((item, index) => (
              <option key={item.label} value={index}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="outline"
          disabled={busy || !(city.trim() || settings.weather_city.trim())}
          onClick={() => void load()}
        >
          {busy ? "Получаю прогноз…" : "Проверить погоду"}
        </button>
      </div>
      <p className="help">
        Проверка — отдельный запрос для указанного места; она не меняет основной
        город и разрешение в чате. Отправляются название места и его координаты,
        без истории и документов. Геолокация автоматически не определяется.
        Open-Meteo / GeoNames; свободный API для некоммерческого использования.
      </p>
      {error && <p role="alert">{error}</p>}
      {forecast && (
        <section
          className="weather-forecast"
          aria-label="Прогноз погоды"
          aria-live="polite"
        >
          <h3>{forecast.place}</h3>
          <p className="help">
            Проверено {new Date(forecast.checked_at).toLocaleString("ru-RU")} ·
            время места: {forecast.timezone}
          </p>
          {forecast.current && (
            <div className="weather-current">
              <strong>{temperature(forecast.current.temperature)}C</strong>
              <div>
                {forecast.current.condition}
                <br />
                Ощущается как {temperature(forecast.current.feels_like)}C ·
                ветер {forecast.current.wind.toLocaleString("ru-RU")} м/с
                <br />
                <small>
                  Расчёт на {forecast.current.time.replace("T", " ")} ·{" "}
                  {forecast.timezone}
                </small>
              </div>
            </div>
          )}
          <div className="weather-days">
            {forecast.days.map((day) => (
              <article key={day.date}>
                <strong>
                  {new Intl.DateTimeFormat("ru-RU", {
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                    timeZone: "UTC",
                  }).format(new Date(day.date + "T12:00:00Z"))}
                </strong>
                <p>{day.condition}</p>
                <b>
                  {temperature(day.low)}…{temperature(day.high)}C
                </b>
                <small>Осадки: {day.rain}%</small>
              </article>
            ))}
          </div>
          <p className="help">
            Модельный прогноз Open-Meteo. Удалённая проверка не заменяет
            показания местного термометра.
          </p>
          <p className="help">
            Источники: Open-Meteo · GeoNames. В ответах чата сохраняются ссылки
            и время получения.
          </p>
        </section>
      )}
    </section>
  );
}
