import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  server: {
    open: "/app/",
    proxy: {
      "^/(auth|admin|publisher|producer|worker-management|worker/v1|jobs|job-types|catalog|management)": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    exclude: ["e2e/**", "node_modules/**"],
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    globals: true,
  },
});
