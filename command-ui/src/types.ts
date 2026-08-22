export type ToolDef = {
  id: string;
  name: string;
  source: string;
  enabled: boolean;
  description?: string;
};

export type BotConfig = {
  meta: {
    id: string;
    name: string;
    role: string;
    roleLabel: string;
    avatar: string;
    status: string;
    scriptLines?: number;
    featureTags?: string[];
  };
  identity: {
    name: string;
    discord_id: string;
    channel_id: string;
    service: string;
    script: string;
    tier: string;
  };
  llm: Record<string, unknown>;
  prompt: Record<string, unknown>;
  tools: ToolDef[];
  guardrails?: Record<string, unknown>;
  scheduler_enabled?: boolean;
  memory?: Record<string, unknown>;
  voice?: Record<string, unknown> | null;
  mcp?: { servers?: Array<Record<string, unknown>> };
  multi_agent?: Record<string, unknown>;
  self_healing?: Record<string, unknown> | null;
  self_improvement?: Record<string, unknown> | null;
};

export type FleetConfig = {
  version: number;
  last_modified: string;
  modified_by?: string;
  fleet_protocol?: Record<string, unknown>;
  conversation?: Record<string, unknown>;
  context_builder?: Record<string, unknown>;
  scheduler?: Record<string, unknown>;
  memory_stats?: { memories?: number; entities?: number; facts?: number };
  bots: Record<string, BotConfig>;
  ui_roster?: string[];
};

export type FleetStats = {
  active_bots: number;
  llm_models: number;
  mcp_tools: number;
  nexus_tools?: number;
  memories: number;
  entities: number;
  facts: number;
};

export type ApiResponse<T> = {
  success: boolean;
  data: T;
  errors: string[];
  requires_restart: string[];
  last_modified: string;
};
