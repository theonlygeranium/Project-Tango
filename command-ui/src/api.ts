import type { ApiResponse, BotConfig, FleetConfig, FleetStats } from "./types";

function cfg() {
  const injected = window.__FLEET_UI__ ?? {};
  return {
    base: (injected.apiBase || import.meta.env.VITE_API_BASE || "").replace(/\/$/, ""),
    token: injected.token || import.meta.env.VITE_API_TOKEN || "",
  };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<ApiResponse<T>> {
  const { base, token } = cfg();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${base}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }
  return (await response.json()) as ApiResponse<T>;
}

export async function fetchConfig(): Promise<FleetConfig> {
  const res = await request<FleetConfig>("/api/fleet/config");
  return res.data;
}

export async function fetchStats(): Promise<FleetStats> {
  const res = await request<FleetStats>("/api/fleet/stats");
  return res.data;
}

export async function fetchStatus(): Promise<Record<string, string>> {
  const res = await request<Record<string, string>>("/api/fleet/status");
  return res.data;
}

export async function saveBot(botId: string, body: BotConfig): Promise<ApiResponse<BotConfig>> {
  return request<BotConfig>(`/api/bots/${botId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function restartBot(botId: string): Promise<ApiResponse<Record<string, string>>> {
  return request<Record<string, string>>(`/api/bots/${botId}/restart`, { method: "POST" });
}

export function hasRuntimeToken(): boolean {
  return Boolean(cfg().token);
}
