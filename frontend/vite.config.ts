import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  server: {
    open: "/app/",
    proxy: {
      "^/(auth|admin|publisher|producer|worker-management|jobs|job-types)": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    globals: true,
  },
});
