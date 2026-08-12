import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: the app serves this page at /page/eda/ (one mount per installed
// plugin page), so every asset URL must start there — without it the page
// loads and its bundle 404s, which reads as a blank page with no error
// anywhere useful.
//
// outDir: the build lands INSIDE the Python package, because that is how it
// travels — the wheel carries nl2sql_eda/webdist/, the plugin's page entry
// point points at it, and installing the package is what puts the page on
// the app. Committed to the repo so nobody needs Node to install this.
//
// dev: `npm run dev` serves on :5173 with /api proxied to the FastAPI
// process — the same workflow as the app's own frontends.
export default defineConfig({
  plugins: [react()],
  base: "/page/eda/",
  build: {
    outDir: "../nl2sql_eda/webdist",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
});
