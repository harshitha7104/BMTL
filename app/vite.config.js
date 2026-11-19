import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",   // security audit L-09: never expose the dev server to the network
    port: 3000,
    strictPort: true,
    hmr: {
      port: 3000,
    },
  },
});
