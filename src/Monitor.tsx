import { useEffect, useState } from "react";
import { request } from "./api";

type Metric = number | null;
type Metrics = { cpu: Metric; ram: Metric; private: Metric; vram: Metric };
type Summary = {
  seconds: number;
  cpu: Metric;
  ram_peak: Metric;
  private_peak: Metric;
};
type Statistics = { work?: Summary; idle?: Summary };
type Point = { time: number; cpu: Metric; ram: Metric; active: boolean };
type Row = Metrics & {
  id: string;
  name: string;
  category: string;
  state: string;
  active: boolean;
  shared?: string;
  external: boolean;
  location?: string;
  allocation?: number;
  pids: number[];
  calls?: { count: number; seconds: number };
  statistics: Statistics;
};
type Snapshot = {
  time: number;
  started: number;
  interval: number;
  cores: number;
  app: Metrics & { active: boolean; statistics: Statistics };
  system: {
    cpu: Metric;
    ram_used: number;
    ram_total: number;
    commit: { used: number; total: number } | null;
  };
  gpu: {
    devices: { name: string; percent: number; used: number; total: number }[];
    note: string;
  };
  history: Point[];
  rows: Row[];
  ollama_note: string | null;
};
const percent = (value: Metric) =>
  value === null ? "—" : value.toFixed(1) + "%";
const bytes = (value: Metric) =>
  value === null
    ? "—"
    : value >= 1024 ** 3
      ? (value / 1024 ** 3).toFixed(2) + " ГБ"
      : (value / 1024 ** 2).toFixed(0) + " МБ";

function useMonitor(compact = false) {
  const [data, setData] = useState<Snapshot>();
  const [error, setError] = useState("");
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController | undefined;
    async function update() {
      clearTimeout(timer);
      if (disposed || document.hidden || controller) return;
      controller = new AbortController();
      try {
        const value = await request<Snapshot>(
          "/monitor" + (compact ? "?compact=true" : ""),
          "GET",
          undefined,
          controller.signal,
        );
        if (!disposed) {
          setData(value);
          setError("");
        }
      } catch (reason) {
        if (!disposed && !controller.signal.aborted)
          setError(String(reason instanceof Error ? reason.message : reason));
      } finally {
        controller = undefined;
        if (!disposed && !document.hidden)
          timer = setTimeout(update, compact ? 5000 : 2000);
      }
    }
    const visibility = () => {
      if (document.hidden) {
        clearTimeout(timer);
        controller?.abort();
      } else void update();
    };
    void update();
    document.addEventListener("visibilitychange", visibility);
    return () => {
      disposed = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [compact]);
  return { data, error };
}

export function ResourceBadge({ onOpen }: { onOpen: () => void }) {
  const { data, error } = useMonitor(true);
  return (
    <button
      className="resource-badge"
      aria-label="Открыть мониторинг нагрузки"
      title={error || "Процессы WileyAI · CPU / ОЗУ"}
      onClick={onOpen}
    >
      ▥{" "}
      {data && !error
        ? `${percent(data.app.cpu)} · ${bytes(data.app.ram)}`
        : "Нагрузка"}
    </button>
  );
}

function Chart({
  points,
  metric,
  label,
  max,
  format,
}: {
  points: Point[];
  metric: "cpu" | "ram";
  label: string;
  max: number;
  format: (value: Metric) => string;
}) {
  // null is a gap, not a made-up zero. Fixed time scale preserves gaps between samples.
  const latest = points.at(-1)?.time || 0;
  const first = Math.min(points[0]?.time || latest, latest - 60);
  const x = (time: number) =>
    10 + ((time - first) / Math.max(1, latest - first)) * 580;
  const y = (value: number) =>
    110 - Math.min(1, value / Math.max(1, max)) * 100;
  let path = "";
  let pen = false;
  for (const point of points) {
    const value = point[metric];
    if (value === null) {
      pen = false;
      continue;
    }
    path += `${pen ? "L" : "M"}${x(point.time).toFixed(1)},${y(value).toFixed(1)} `;
    pen = true;
  }
  return (
    <figure className="resource-chart">
      <figcaption>
        {label}
        <strong>{format(points.at(-1)?.[metric] ?? null)}</strong>
      </figcaption>
      <svg
        viewBox="0 0 600 125"
        role="img"
        aria-label={`${label}. Линия — нагрузка, зелёные отметки — работа моделей.`}
      >
        {[10, 60, 110].map((value) => (
          <line
            key={value}
            x1="10"
            x2="590"
            y1={value}
            y2={value}
            className="resource-grid"
          />
        ))}
        {points
          .filter((point) => point.active)
          .map((point) => (
            <rect
              key={point.time}
              x={x(point.time)}
              y="10"
              width="3"
              height="100"
              className="resource-work"
            />
          ))}
        <path d={path} fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
      <small>
        {new Date(first * 1000).toLocaleTimeString("ru-RU")} —{" "}
        {new Date(latest * 1000).toLocaleTimeString("ru-RU")}
      </small>
    </figure>
  );
}

function Comparison({ statistics }: { statistics: Statistics }) {
  return (
    <div className="resource-comparison">
      {(["work", "idle"] as const).map((phase) => {
        const value = statistics[phase];
        return (
          <div key={phase}>
            <strong>
              {phase === "work" ? "При работе моделей" : "В простое"}
            </strong>
            {value ? (
              <span>
                CPU в среднем {percent(value.cpu)} · пик ОЗУ{" "}
                {bytes(value.ram_peak)} · пик выделенной{" "}
                {bytes(value.private_peak)}
              </span>
            ) : (
              <span>Ещё нет замеров</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function MonitorPanel() {
  const { data, error } = useMonitor();
  return (
    <section className="page scroll-page resource-panel">
      <div className="page-heading">
        <div>
          <span className="eyebrow">СИСТЕМА</span>
          <h1>Нагрузка</h1>
          <p>WileyAI, модели и свободные ресурсы компьютера.</p>
        </div>
      </div>
      {error && (
        <p role="status" className="help">
          {error}{" "}
          {data ? "Показан последний успешный замер." : "Повторяю подключение…"}
        </p>
      )}
      {!data ? (
        <p className="help">Собираю показатели…</p>
      ) : (
        <>
          <div className="resource-cards">
            <article>
              <span>CPU WileyAI</span>
              <strong>{percent(data.app.cpu)}</strong>
              <small>Из всей мощности CPU · {data.cores} потоков</small>
            </article>
            <article>
              <span>ОЗУ WileyAI</span>
              <strong>{bytes(data.app.ram)}</strong>
              <small>Сумма рабочих наборов процессов</small>
            </article>
            <article>
              <span>Выделено WileyAI</span>
              <strong>{bytes(data.app.private)}</strong>
              <small>Частная память: ОЗУ и файл подкачки</small>
            </article>
            <article>
              <span>Ресурсы компьютера</span>
              <strong>CPU {percent(data.system.cpu)}</strong>
              <small>
                ОЗУ {bytes(data.system.ram_used)} /{" "}
                {bytes(data.system.ram_total)}
              </small>
              {data.system.commit && (
                <small
                  className={
                    data.system.commit.used / data.system.commit.total > 0.9
                      ? "resource-pressure"
                      : ""
                  }
                >
                  Выделено Windows {bytes(data.system.commit.used)} /{" "}
                  {bytes(data.system.commit.total)}
                </small>
              )}
            </article>
          </div>
          <p className="help">
            {data.app.active
              ? "Сейчас модели работают."
              : "Сейчас модели в простое."}{" "}
            Замер каждые {data.interval} с, история до 10 минут с запуска
            программы. Монитор не запускает модели. Обновлено{" "}
            {new Date(data.time * 1000).toLocaleTimeString("ru-RU")}.
          </p>
          <Comparison statistics={data.app.statistics} />
          <div className="resource-charts">
            <Chart
              points={data.history}
              metric="cpu"
              label="CPU WileyAI"
              max={100}
              format={percent}
            />
            <Chart
              points={data.history}
              metric="ram"
              label="ОЗУ WileyAI"
              max={
                Math.max(
                  256 * 1024 ** 2,
                  ...data.history.map((point) => point.ram || 0),
                ) * 1.1
              }
              format={bytes}
            />
          </div>
          <h2>Программа и модели</h2>
          <div className="resource-table-wrap">
            <table className="resource-table">
              <thead>
                <tr>
                  <th>Компонент</th>
                  <th>Состояние</th>
                  <th>CPU</th>
                  <th>ОЗУ</th>
                  <th>Выделено</th>
                  <th>Видеопамять</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.name}</strong>
                      <small>
                        {row.category}
                        {row.external
                          ? " · общий сервер, вне суммы WileyAI"
                          : ""}
                        {row.shared ? " · внутри ядра" : ""}
                        {row.location === "cloud" ? " · удалённый сервер" : ""}
                      </small>
                      {row.pids.length > 0 && (
                        <small>PID: {row.pids.join(", ")}</small>
                      )}
                      <details>
                        <summary>Работа и простой</summary>
                        <Comparison statistics={row.statistics} />
                        {row.calls && (
                          <small>
                            Завершено операций: {row.calls.count} · всего{" "}
                            {row.calls.seconds.toFixed(1)} с
                          </small>
                        )}
                      </details>
                    </td>
                    <td className={row.active ? "resource-active" : ""}>
                      {row.state}
                    </td>
                    <td>{percent(row.cpu)}</td>
                    <td>{bytes(row.ram)}</td>
                    <td>{bytes(row.private)}</td>
                    <td>
                      {bytes(row.vram)}
                      {row.allocation !== undefined && (
                        <small>Ollama выделила {bytes(row.allocation)}</small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="help">
            Silero, Piper и Whisper работают внутри ядра: их отдельные CPU и ОЗУ
            не измеряются средствами процесса. Общие затраты показаны в строке
            «Ядро и общие модели». Qwen3-TTS измеряется отдельно. Работа и
            простой определяются запросами WileyAI; общий сервер может выполнять
            запросы других программ. Рабочие наборы могут включать общие
            страницы памяти. «—» означает, что отдельный замер недоступен.
          </p>
          {data.ollama_note && <p className="help">{data.ollama_note}</p>}
          <h2>Видеокарта компьютера</h2>
          <div className="resource-cards">
            {data.gpu.devices.map((gpu) => (
              <article key={gpu.name}>
                <span>{gpu.name}</span>
                <strong>{percent(gpu.percent)}</strong>
                <small>
                  Видеопамять {bytes(gpu.used)} / {bytes(gpu.total)}
                </small>
              </article>
            ))}
          </div>
          <p className="help">
            {data.gpu.note} Показатели драйвера и список загруженных моделей
            обновляются раз в 6 с. Память Ollama — её собственная оценка
            выделения, она не прибавляется к измерению драйвера.
          </p>
        </>
      )}
    </section>
  );
}
