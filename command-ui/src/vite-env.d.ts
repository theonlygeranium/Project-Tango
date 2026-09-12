/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_API_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  __FLEET_UI__?: {
    apiBase?: string;
    token?: string;
    version?: string;
  };
}
