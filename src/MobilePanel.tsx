import { useEffect, useMemo, useState } from "react";
import { request } from "./api";
import { qrcodegen } from "./vendor/qrcodegen";

type State = {
  running: boolean;
  enabled: boolean;
  error: string;
  port: number;
  addresses: string[];
  pairing: boolean;
  devices: { id: string; name: string }[];
};

function PairingCode({ value }: { value: string }) {
  const qr = useMemo(
    () => qrcodegen.QrCode.encodeText(value, qrcodegen.QrCode.Ecc.MEDIUM),
    [value],
  );
  const path = useMemo(() => {
    const cells: string[] = [];
    for (let y = 0; y < qr.size; y++)
      for (let x = 0; x < qr.size; x++)
        if (qr.getModule(x, y)) cells.push(`M${x + 4},${y + 4}h1v1h-1z`);
    return cells.join("");
  }, [qr]);
  return (
    <svg
      aria-label="Код подключения Android"
      role="img"
      viewBox={`0 0 ${qr.size + 8} ${qr.size + 8}`}
      style={{
        width: "min(100%, 320px)",
        background: "white",
        borderRadius: 8,
      }}
    >
      <path d={path} fill="black" />
    </svg>
  );
}

export function MobilePanel() {
  const [state, setState] = useState<State | null>(null);
  const [address, setAddress] = useState("");
  const [pair, setPair] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showText, setShowText] = useState(false);
  async function refresh() {
    const next = await request<State>("/mobile/status");
    setState(next);
    setAddress((previous) =>
      next.addresses.includes(previous) ? previous : next.addresses[0] || "",
    );
    return next;
  }
  useEffect(() => {
    void refresh().catch((e) => setError(String(e.message || e)));
  }, []);
  useEffect(() => {
    if (!pair) return;
    const timer = setTimeout(() => {
      setPair("");
      void refresh();
    }, 300000);
    return () => clearTimeout(timer);
  }, [pair]);
  useEffect(() => {
    if (!pair || !state?.running) return;
    const timer = setInterval(() => {
      void refresh()
        .then((next) => {
          if (!next.pairing) setPair("");
        })
        .catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [pair, state?.running]);
  async function action(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card">
      <h2>WileyAI на телефоне</h2>
      <p>
        Подключите Android к этому компьютеру. Дома устройства должны быть в
        одной сети Wi-Fi; через мобильный интернет подключите оба устройства к
        одной сети Tailscale.
      </p>
      <p className="help">
        Компьютер и WileyAI должны быть включены. Телефон получает отдельный
        доступ, который здесь можно отозвать.
      </p>
      <p role="status">
        {state?.running
          ? `Подключение включено · порт ${state.port}`
          : state?.enabled ? "Подключение не запустилось" : "Подключение выключено"}
      </p>
      {state?.error && <p className="error" role="alert">{state.error}</p>}
      <div className="button-row">
        <button
          className="outline"
          disabled={busy}
          onClick={() =>
            action(async () => {
              await request(
                state?.running || state?.enabled ? "/mobile/stop" : "/mobile/start",
                "POST",
              );
              setPair("");
              await refresh();
            })
          }
        >
          {state?.running || state?.enabled ? "Выключить подключение" : "Включить подключение"}
        </button>
        <button
          className="outline"
          disabled={busy}
          onClick={() => action(refresh)}
        >
          Обновить адреса
        </button>
      </div>
      {state?.running && (
        <>
          <label>
            Адрес компьютера
            <select
              aria-label="Адрес компьютера для телефона"
              value={address}
              onChange={(e) => {
                setAddress(e.target.value);
                setPair("");
              }}
            >
              <option value="">Выберите адрес</option>
              {state.addresses.map((ip) => (
                <option key={ip} value={ip}>
                  {ip.startsWith("100.")
                    ? `${ip} · Tailscale`
                    : `${ip} · локальная сеть`}
                </option>
              ))}
            </select>
          </label>
          {!state.addresses.length && (
            <p className="help">
              Не найден адрес локальной сети. Подключите Wi-Fi или запустите
              Tailscale и обновите адреса.
            </p>
          )}
          <button
            className="primary"
            disabled={busy || !address}
            onClick={() =>
              action(async () => {
                const result = await request<{ uri: string }>(
                  `/mobile/pairing?address=${encodeURIComponent(address)}`,
                  "POST",
                );
                setPair(result.uri);
                setShowText(false);
                await refresh();
              })
            }
          >
            Показать код для телефона
          </button>
          {pair && (
            <div style={{ marginTop: 16 }}>
              <PairingCode value={pair} />
              <p className="help">
                Откройте камеру телефона, наведите на код и откройте ссылку в
                WileyAI. Код одноразовый, действует 5 минут.
              </p>
              <button
                className="outline"
                onClick={() => setShowText(!showText)}
              >
                {showText
                  ? "Скрыть ссылку"
                  : "Показать ссылку для ручного ввода"}
              </button>
              {showText && (
                <textarea
                  aria-label="Одноразовая ссылка подключения"
                  readOnly
                  value={pair}
                  rows={4}
                />
              )}
            </div>
          )}
        </>
      )}
      <h3>Подключённые телефоны</h3>
      {state?.devices.length ? (
        state.devices.map((device) => (
          <div className="installed-row" key={device.id}>
            <span>{device.name}</span>
            <button
              className="outline"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await request(`/mobile/devices/${device.id}`, "DELETE");
                  await refresh();
                })
              }
            >
              Отключить
            </button>
          </div>
        ))
      ) : (
        <p className="help">Телефонов пока нет.</p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
