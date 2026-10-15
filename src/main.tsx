import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { init } from "./api";
import "./style.css";

init()
  .then(() => createRoot(document.getElementById("root")!).render(<App />))
  .catch((error) => {
    const root = document.getElementById("root")!;
    root.className = "startup-error";
    root.textContent = error.message;
  });
