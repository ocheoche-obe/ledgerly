import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  test: {
    // jsdom gives the smoke test a DOM to render React into; no browser needed.
    environment: "jsdom",
  },
});
