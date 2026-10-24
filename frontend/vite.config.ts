import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// In dev the Django backend runs on :8000; proxying /api and /media keeps the SPA
// same-origin, so no CORS and no absolute URLs are needed.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_BACKEND_URL || "http://localhost:8000";
  return {
    plugins: [react()],
    resolve: { alias: { "@": path.resolve(__dirname, "src") } },
    server: {
      host: true,
      port: 5173,
      proxy: {
        "/api": { target: backend, changeOrigin: true },
        "/media": { target: backend, changeOrigin: true },
        "/admin": { target: backend, changeOrigin: true },
        "/static": { target: backend, changeOrigin: true },
      },
    },
    build: {
      chunkSizeWarningLimit: 1200,
    },
  };
});
