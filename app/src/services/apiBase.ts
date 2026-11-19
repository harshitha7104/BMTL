// Backend base URL.
// - VITE_API_BASE_URL wins when set (e.g. a separate API host).
// - `npm run dev` talks to a backend on http://localhost:8000.
// - A production build is served by the backend itself, so it uses the same origin.
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '');
