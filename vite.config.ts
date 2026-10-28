import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  // Maps stay local for debugging; the page does not reference them and the
  // installer excludes them (electron-builder.yml).
  build: { outDir: "dist", sourcemap: "hidden", assetsInlineLimit: 0 },
});
