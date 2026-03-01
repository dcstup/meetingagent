import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/dashboard/",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
      "/railway-api": {
        target: "https://backboard.railway.app",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/railway-api/, "/graphql/v2"),
      },
    },
  },
});
