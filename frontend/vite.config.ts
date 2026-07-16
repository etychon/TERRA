import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(here, "../src/terra/static/dist"),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        "devices-grid": path.resolve(here, "src/devices/main.tsx"),
        "events-grid": path.resolve(here, "src/events/main.tsx"),
      },
      output: {
        entryFileNames: "[name].js",
        assetFileNames: "[name][extname]",
      },
    },
  },
});
