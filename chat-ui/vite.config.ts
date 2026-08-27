import path from "node:path";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import ui from "@nuxt/ui/vite";

export default defineConfig({
  base: "/static/chat/",
  plugins: [
    vue(),
    ui({
      ui: {
        colors: { primary: "emerald", neutral: "zinc" },
      },
    }),
  ],
  resolve: {
    alias: {
      "@sheet": path.resolve(import.meta.dirname, "../ui/src/gristSheet.ts"),
    },
  },
  build: {
    outDir: "../sidecar/static/chat",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "chunk-[name].js",
        assetFileNames: (info) =>
          String(info.name || "").endsWith(".css") ? "app.css" : "assets/[name][extname]",
      },
    },
  },
});
