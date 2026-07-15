import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// L'app sert web/public/ à la racine : /library/<slug>/… est donc accessible.
export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5173 },
});
