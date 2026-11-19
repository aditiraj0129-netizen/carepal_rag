import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, /api/* is proxied to the FastAPI backend, so no CORS configuration is needed.
const backend = "http://127.0.0.1:8000"; // change here if the API runs elsewhere

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: backend, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  preview: {
    port: 5173,
    proxy: { "/api": { target: backend, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
