import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { init } from "./api";
import "./style.css";

const root = createRoot(document.getElementById("root")!);
function start() {
  root.render(
    <div className="loading">
      <div className="logo-mark">W</div>
      <p>Запускаю локальное ядро…</p>
      <div
        className="startup-progress"
        role="progressbar"
        aria-label="Подключение к локальному ядру"
      >
        <span />
      </div>
    </div>,
  );
  void init()
    .then(() => root.render(<App />))
    .catch((error: unknown) =>
      root.render(
        <div className="startup-error">
          <div className="logo-mark">W</div>
          <h1>Не удалось подключиться к локальному ядру</h1>
          <p role="alert">
            {error instanceof Error ? error.message : "Перезапустите WileyAI."}
          </p>
          <button onClick={start}>Повторить подключение</button>
        </div>,
      ),
    );
}
start();
