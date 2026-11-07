import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  root: "src",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      "@sxarf/inference": resolve(import.meta.dirname, "plugins/inference/src/index.ts"),
    },
  },
});
