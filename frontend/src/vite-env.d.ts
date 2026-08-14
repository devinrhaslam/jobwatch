/// <reference types="vite/client" />

interface ImportMetaEnv {
  // The backend's absolute URL in production; unset in dev (falls back to /api).
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
