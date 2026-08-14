import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Go backend runs on :8080 and sets no CORS headers, so in dev we proxy
// /api/* to it (stripping the prefix). In production the frontend and API sit
// behind one gateway, or the backend grows a CORS middleware — either way the
// app only ever calls same-origin /api.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
