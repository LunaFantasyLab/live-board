import { defineConfig } from "vite";
// 本地预览：先在另一个终端跑  python3 ../writer/liveboard.py serve  （默认 127.0.0.1:4380），再 npm run dev
export default defineConfig({
  base: "/",
  build: { outDir: "dist", target: "es2022", chunkSizeWarningLimit: 900 },
  server: { host: "127.0.0.1", proxy: { "/api": "http://127.0.0.1:4380", "/__board": "http://127.0.0.1:4380" } },
});
