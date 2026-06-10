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
      input: path.resolve(here, "src/devices/main.tsx"),
      output: {
        entryFileNames: "devices-grid.js",
        assetFileNames: "devices-grid.[ext]",
      },
    },
  },
});
