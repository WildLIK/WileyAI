import { useEffect, useState } from "react";
import { request, type Settings } from "./api";

type Status = {
  last_backup?: string;
  path?: string;
  directory: string;
  error: string;
  quiet_now: boolean;
};

export function BackgroundSettings({
  settings,
  onChange,
  onError,
}: {
  settings: Settings;
  onChange: (value: Settings) => void;
  onError: (error: unknown) => void;
}) {
  const [startup, setStartup] = useState<{
    available: boolean;
    enabled: boolean;
  }>();
  const [working, setWorking] = useState(false);
  const [status, setStatus] = useState<Status>();
  useEffect(() => {
    let disposed = false;
    void (
      window.wiley.startup
        ? window.wiley.startup()
        : Promise.resolve({ available: false, enabled: false })
    )
      .then((value) => {
        if (!disposed) setStartup(value);
      })
      .catch(onError);
    const load = () =>
      request<Status>("/background")
        .then((value) => {
          if (!disposed) setStatus(value);
        })
        .catch(onError);
    void load();
    const interval = setInterval(() => void load(), 10000);
    return () => {
      disposed = true;
      clearInterval(interval);
    };
  }, [onError]);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return (
    <div className="card">
      <h2>Работа в фоне</h2>
      <label className="checkbox">
        <input
          type="checkbox"
          disabled={working || !startup?.available}
          checked={startup?.enabled || false}
          onChange={async (event) => {
            setWorking(true);
            try {
              setStartup(await window.wiley.setStartup(event.target.checked));
            } catch (error) {
              onError(error);
            } finally {
              setWorking(false);
            }
          }}
        />
        Запускать WileyAI при входе в Windows
      </label>
      <p className="help">
        Применяется сразу. Автозапуск открывает значок в трее; разговор и
        микрофон автоматически не включаются.{" "}
        {startup && !startup.available
          ? "Доступно в установленной версии Windows."
          : ""}
      </p>
      <label>
        Часовой пояс расписаний
        <input
          value={settings.background_timezone}
          onChange={(event) =>
            onChange({ ...settings, background_timezone: event.target.value })
          }
        />
      </label>
      <button
        className="subtle"
        onClick={() => onChange({ ...settings, background_timezone: zone })}
      >
        Использовать часовой пояс компьютера · {zone}
      </button>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.quiet_enabled}
          onChange={(event) =>
            onChange({ ...settings, quiet_enabled: event.target.checked })
          }
        />
        Тихие часы уведомлений
      </label>
      <div className="two-columns">
        <label>
          Начало
          <input
            type="time"
            value={settings.quiet_start}
            onChange={(event) =>
              onChange({ ...settings, quiet_start: event.target.value })
            }
          />
        </label>
        <label>
          Окончание
          <input
            type="time"
            value={settings.quiet_end}
            onChange={(event) =>
              onChange({ ...settings, quiet_end: event.target.value })
            }
          />
        </label>
      </div>
      <p className="help">
        Напоминания остаются в очереди и приходят после окончания тихих часов.
        Можно задать интервал через полночь; одинаковое время означает весь
        день. Ответы по вашей команде и озвучка не отключаются.
      </p>
      <label>
        Автоматические резервные копии
        <select
          aria-label="Автоматические резервные копии"
          value={settings.backup_schedule}
          onChange={(event) =>
            onChange({
              ...settings,
              backup_schedule: event.target
                .value as Settings["backup_schedule"],
            })
          }
        >
          <option value="off">Выключены</option>
          <option value="daily">Каждый день</option>
          <option value="weekly">Раз в неделю</option>
        </select>
      </label>
      <label>
        Время копирования
        <input
          type="time"
          value={settings.backup_time}
          onChange={(event) =>
            onChange({ ...settings, backup_time: event.target.value })
          }
        />
      </label>
      {settings.backup_schedule === "weekly" && (
        <label>
          День недели
          <select
            value={settings.backup_weekday}
            onChange={(event) =>
              onChange({
                ...settings,
                backup_weekday: Number(event.target.value),
              })
            }
          >
            {[
              "Понедельник",
              "Вторник",
              "Среда",
              "Четверг",
              "Пятница",
              "Суббота",
              "Воскресенье",
            ].map((name, index) => (
              <option key={index} value={index}>
                {name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Сколько автоматических копий хранить
        <input
          type="number"
          min={1}
          max={30}
          value={settings.backup_keep}
          onChange={(event) =>
            onChange({ ...settings, backup_keep: Number(event.target.value) })
          }
        />
      </label>
      <p className="help">
        Пока WileyAI запущена, сохраняется проверенная копия в каталоге данных.
        После пропущенного срока выполняется одна копия. Старые автоматические
        копии удаляются только после успешного сохранения новой; ручные и
        защитные копии сохраняются. Весов моделей в копии нет.
      </p>
      {status && (
        <>
          <p>Каталог: {status.directory}</p>
          <p role="status">
            {status.error ||
              (status.last_backup
                ? "Последняя копия: " +
                  new Date(status.last_backup).toLocaleString("ru-RU")
                : "Автоматических копий ещё нет")}
            {status.quiet_now ? " · Сейчас тихие часы" : ""}
          </p>
        </>
      )}
      <p className="help">
        Расписание и тихие часы применяются кнопкой «Сохранить» вверху настроек.
      </p>
    </div>
  );
}
