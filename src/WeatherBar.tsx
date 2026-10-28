import { useEffect, useMemo, useState } from "react";
import { request, type Settings, errorText } from "./api";

type Weather = {
  place: string;
  timezone: string;
  checked_at: string;
  current: {
    temperature: number;
    feels_like: number;
    condition: string;
    time: string;
  } | null;
};
type State = { key: string; value?: Weather; error?: string; busy?: boolean };
const degrees = (value: number) =>
  `${value > 0 ? "+" : ""}${value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}°`;

function WeatherIcon({ condition }: { condition: string }) {
  const kind = /гроза|град/i.test(condition)
    ? "thunder"
    : /снег|снеж/i.test(condition)
      ? "snow"
      : /дожд|ливен|морос/i.test(condition)
        ? "rain"
        : /туман|измороз/i.test(condition)
          ? "fog"
          : /ясно/i.test(condition)
            ? "sun"
            : "cloud";
  return (
    <svg
      className="weather-icon"
      data-weather-icon={kind}
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {kind === "sun" ? (
        <>
          <circle cx="16" cy="16" r="6" />
          <path d="M16 3v3m0 20v3M3 16h3m20 0h3M7 7l2 2m14 14 2 2M7 25l2-2M23 9l2-2" />
        </>
      ) : (
        <>
          <path d="M7 21a5 5 0 0 1 0-10 8 8 0 0 1 15-1 5.5 5.5 0 1 1 2 11H7Z" />
          {kind === "rain" && <path d="m10 25-1 3m8-3-1 3m8-3-1 3" />}
          {kind === "snow" && (
            <path d="M10 25v5m-2-4 4 3m0-3-4 3m14-4v5m-2-4 4 3m0-3-4 3" />
          )}
          {kind === "thunder" && <path d="m17 18-4 7h5l-3 6" />}
          {kind === "fog" && <path d="M5 25h22M9 29h14" />}
        </>
      )}
    </svg>
  );
}

export function WeatherBar({
  settings,
  onOpen,
}: {
  settings?: Settings;
  onOpen(): void;
}) {
  const enabled = Boolean(
    settings?.weather_enabled && settings.weather_city.trim(),
  );
  const key = enabled
    ? `${settings!.weather_city.trim()}|${settings!.web_dns}`
    : "";
  const [state, setState] = useState<State>({ key: "" });
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    let disposed = false,
      active: AbortController | undefined,
      next = 0;
    setState({ key });
    async function refresh() {
      if (!key || active || document.hidden || Date.now() < next) return;
      active = new AbortController();
      const controller = active;
      setState((value) => ({ ...value, key, busy: true }));
      try {
        const value = await request<Weather>(
          "/weather/current",
          "GET",
          undefined,
          AbortSignal.any([controller.signal, AbortSignal.timeout(45000)]),
        );
        if (!value.current) throw new Error("Сервис не вернул текущую погоду");
        if (!disposed && !controller.signal.aborted) {
          setState({ key, value });
          next = Date.now() + 30 * 60 * 1000;
        }
      } catch (error) {
        if (!disposed && !controller.signal.aborted) {
          setState((value) => ({
            ...value,
            key,
            busy: false,
            error: errorText(error),
          }));
          next = Date.now() + 5 * 60 * 1000;
        }
      } finally {
        if (active === controller) active = undefined;
      }
    }
    const tick = () => {
      setNow(Date.now());
      void refresh();
    };
    tick();
    const timer = setInterval(tick, 60000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      disposed = true;
      active?.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [key]);
  const current = state.key === key ? state : { key };
  const weather = current.value,
    reading = weather?.current;
  const timeZone = weather?.timezone;
  const dateFormat = useMemo(
    () =>
      new Intl.DateTimeFormat("ru-RU", {
        day: "numeric",
        month: "short",
        ...(timeZone ? { timeZone } : {}),
      }),
    [timeZone],
  );
  const date = dateFormat.format(now);
  const details =
    weather && reading
      ? `${weather.place}. ${reading.condition}. ${degrees(reading.temperature)}C, ощущается как ${degrees(reading.feels_like)}C. Расчёт: ${reading.time.replace("T", " ")} (${weather.timezone}). Open-Meteo; получено ${new Date(weather.checked_at).toLocaleString("ru-RU")}.`
      : enabled
        ? current.error
          ? "Погода недоступна. " + current.error
          : "Получаю погоду сохранённого города…"
        : "Укажите город и включите погоду в настройках";
  return (
    <div
      className="weather-bar"
      role="region"
      aria-label="Погода в верхней панели"
      data-unavailable={Boolean(current.error)}
    >
      <time className="weather-date">{date}</time>
      <button
        className="weather-summary"
        onClick={onOpen}
        title={
          details +
          (reading && current.error
            ? " Нет обновления: " + current.error
            : "") +
          " Открыть настройки погоды."
        }
        aria-label={details + " Открыть настройки погоды"}
      >
        <WeatherIcon condition={reading?.condition || ""} />
        <span className="weather-temperature">
          {reading
            ? degrees(reading.temperature) + "C"
            : enabled
              ? current.error
                ? "Нет данных"
                : "…"
              : "Погода"}
        </span>
        <span className="weather-description">
          <span>
            {reading?.condition ||
              (enabled
                ? current.error
                  ? "Не удалось обновить"
                  : "Получаю прогноз"
                : "Настроить")}
          </span>
          <small>
            {reading
              ? `Ощущается ${degrees(reading.feels_like)}C${current.error ? " · нет обновления" : ""}`
              : enabled
                ? settings!.weather_city
                : "Выбрать город"}
          </small>
        </span>
      </button>
    </div>
  );
}
