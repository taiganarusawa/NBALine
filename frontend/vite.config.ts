import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run build` writes the finished page to dist/, which webapp.py serves (NBALine.bat needs nothing else).
// `npm run dev` is for working on the page: instant reloads on http://localhost:5173, with /api calls
// passed on to a running NBALine.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:5055" } },
  build: { outDir: "dist", emptyOutDir: true },
});
