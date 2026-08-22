import { useEffect, useMemo, useState } from "react";
import { fetchConfig, fetchStats, fetchStatus, hasRuntimeToken, restartBot, saveBot } from "./api";
import { orderedBotIds, ROLE_COLOR } from "./roster";
import type { BotConfig, FleetConfig, FleetStats } from "./types";

const TABS = ["identity", "llm", "tools", "prompt", "memory", "voice", "power"] as const;
type Tab = (typeof TABS)[number];

function stardate(d = new Date()): string {
  const start = new Date(d.getFullYear(), 0, 0).getTime();
  const day = Math.floor((d.getTime() - start) / 86400000);
  return `${d.getFullYear()}.${String(day).padStart(3, "0")}`;
}

export default function App() {
  const [config, setConfig] = useState<FleetConfig | null>(null);
  const [stats, setStats] = useState<FleetStats | null>(null);
  const [liveStatus, setLiveStatus] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("identity");
  const [draft, setDraft] = useState<BotConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [cfg, st, status] = await Promise.all([fetchConfig(), fetchStats(), fetchStatus()]);
      setConfig(cfg);
      setStats(st);
      setLiveStatus(status);
      const ids = orderedBotIds(cfg.bots);
      setSelected((cur) => cur && ids.includes(cur) ? cur : ids[0] ?? null);
    } catch (err) {
      setConfig(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!config || !selected || !config.bots[selected]) {
      setDraft(null);
      return;
    }
    setDraft(structuredClone(config.bots[selected]));
  }, [config, selected]);

  const roster = useMemo(() => (config ? orderedBotIds(config.bots) : []), [config]);

  async function onSave() {
    if (!selected || !draft) return;
    setMessage(null);
    try {
      const res = await saveBot(selected, draft);
      setMessage(res.success ? "Config saved successfully" : res.errors.join("; "));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onRestart() {
    if (!selected) return;
    setMessage(null);
    try {
      const res = await restartBot(selected);
      setMessage(res.success ? `Restarted ${draft?.identity.service ?? selected}` : res.errors.join("; ") || "Restart failed");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">LCARS · Fleet Command Interface</div>
        <div className="stats">
          <span>STARDATE <strong>{stardate()}</strong></span>
          <span>FLEET <strong>{stats?.active_bots ?? "—"}</strong></span>
          <span>MODELS <strong>{stats?.llm_models ?? "—"}</strong></span>
          <span>MCP <strong>{stats?.mcp_tools ?? "—"}</strong></span>
          <span>NEXUS <strong>{stats?.nexus_tools ?? "—"}</strong></span>
        </div>
        <button className="ghost" onClick={() => void load()}>Reload</button>
      </header>

      {error && (
        <div className="error">
          {error}
          {!hasRuntimeToken() ? " — no API token in /ui/config.js or VITE_API_TOKEN." : ""}
          {" "}This console does not fall back to mock data.
        </div>
      )}
      {message && <div className="banner">{message}</div>}

      <div className="layout">
        <aside className="sidebar">
          <div className="section-title">Bot Roster · {roster.length}</div>
          {loading && <div className="field-value">Loading fleet…</div>}
          {roster.map((id) => {
            const bot = config?.bots[id];
            if (!bot) return null;
            const status = liveStatus[id] || liveStatus[id === "voss" ? "dr_voss" : id] || bot.meta.status;
            const color = ROLE_COLOR[bot.meta.role] || ROLE_COLOR.testing;
            return (
              <button
                key={id}
                className={`panel panel-lift bot-card${selected === id ? " active" : ""}`}
                style={{ borderLeftColor: color }}
                onClick={() => { setSelected(id); setTab("identity"); }}
              >
                <div className="name">{bot.meta.name}</div>
                <div className="role">{bot.meta.roleLabel} · {id}</div>
                <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 6 }}>
                  <span className={`status-dot ${status}`} />
                  <span className="field-value">{status}</span>
                </div>
              </button>
            );
          })}
        </aside>

        <main className="main">
          {!draft ? (
            <div className="panel" style={{ padding: 20 }}>
              <h2 className="section-title">Fleet Overview</h2>
              <p>Select a bot. Sentinel is the eighth Nexus card (validation). Dr. Voss uses id <code>voss</code>.</p>
            </div>
          ) : (
            <BotPanel
              draft={draft}
              setDraft={setDraft}
              tab={tab}
              setTab={setTab}
              onSave={() => void onSave()}
              onRestart={() => void onRestart()}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function BotPanel({
  draft,
  setDraft,
  tab,
  setTab,
  onSave,
  onRestart,
}: {
  draft: BotConfig;
  setDraft: (bot: BotConfig) => void;
  tab: Tab;
  setTab: (tab: Tab) => void;
  onSave: () => void;
  onRestart: () => void;
}) {
  return (
    <div>
      <h2 style={{ margin: "0 0 8px" }}>{draft.meta.name}</h2>
      <div className="field-label">{draft.identity.tier} · {draft.meta.id}</div>
      <div className="tabs">
        {TABS.map((item) => (
          <button key={item} className={`tab${tab === item ? " active" : ""}`} onClick={() => setTab(item)}>
            {item}
          </button>
        ))}
      </div>

      {tab === "identity" && (
        <section className="panel" style={{ padding: 16 }}>
          <Field label="Bot Name" value={draft.identity.name} onChange={(v) => setDraft({ ...draft, identity: { ...draft.identity, name: v }, meta: { ...draft.meta, name: v } })} />
          <div className="grid-2">
            <Field label="UI / Nexus ID" value={draft.meta.id} readOnly />
            <Field label="Systemd Service" value={draft.identity.service} onChange={(v) => setDraft({ ...draft, identity: { ...draft.identity, service: v } })} />
            <Field label="Discord Bot ID" value={draft.identity.discord_id} onChange={(v) => setDraft({ ...draft, identity: { ...draft.identity, discord_id: v } })} />
            <Field label="Channel ID" value={draft.identity.channel_id} onChange={(v) => setDraft({ ...draft, identity: { ...draft.identity, channel_id: v } })} />
            <Field label="Script File" value={draft.identity.script} onChange={(v) => setDraft({ ...draft, identity: { ...draft.identity, script: v } })} />
            <Field label="Permission Tier" value={draft.identity.tier} onChange={(v) => setDraft({ ...draft, identity: { ...draft.identity, tier: v } })} />
          </div>
          <div className="field-label">Feature tags</div>
          <div>{(draft.meta.featureTags ?? []).map((tag) => <span key={tag} className="badge" style={{ marginRight: 8 }}>{tag}</span>)}</div>
        </section>
      )}

      {tab === "llm" && (
        <section className="panel" style={{ padding: 16 }}>
          <p className="field-label">Fleet default is <code>writer/palmyra-x6</code> for primary and coding models.</p>
          <div className="grid-2">
            <Field label="Primary Model" value={String(draft.llm.model ?? "")} placeholder="writer/palmyra-x6" onChange={(v) => setDraft({ ...draft, llm: { ...draft.llm, model: v } })} />
            <Field label="Coding Model" value={String(draft.llm.coding_model ?? "")} placeholder="writer/palmyra-x6" onChange={(v) => setDraft({ ...draft, llm: { ...draft.llm, coding_model: v || null } })} />
            <Field label="Temperature" value={String(draft.llm.temperature ?? "")} onChange={(v) => setDraft({ ...draft, llm: { ...draft.llm, temperature: Number(v) } })} />
            <Field label="Max Output Tokens" value={String(draft.llm.max_tokens ?? "")} onChange={(v) => setDraft({ ...draft, llm: { ...draft.llm, max_tokens: Number(v) } })} />
            <Field label="LLM Call Timeout" value={String(draft.llm.llm_timeout ?? "")} onChange={(v) => setDraft({ ...draft, llm: { ...draft.llm, llm_timeout: Number(v) } })} />
            <Field label="Max Agent Iterations" value={String(draft.llm.max_iterations ?? "")} onChange={(v) => setDraft({ ...draft, llm: { ...draft.llm, max_iterations: Number(v) } })} />
          </div>
        </section>
      )}

      {tab === "tools" && (
        <section className="panel" style={{ padding: 16 }}>
          <div className="section-title">Tools · {draft.tools.length}</div>
          {draft.tools.map((tool, index) => (
            <label key={tool.id} className="tool-row">
              <span>
                <strong>{tool.name}</strong>
                <span className="badge" style={{ marginLeft: 8 }}>{tool.source}</span>
                {tool.description ? <div className="field-label" style={{ marginTop: 4 }}>{tool.description}</div> : null}
              </span>
              <input
                type="checkbox"
                checked={tool.enabled}
                style={{ width: "auto" }}
                onChange={(e) => {
                  const tools = draft.tools.slice();
                  tools[index] = { ...tool, enabled: e.target.checked };
                  setDraft({ ...draft, tools });
                }}
              />
            </label>
          ))}
        </section>
      )}

      {tab === "prompt" && (
        <section className="panel" style={{ padding: 16 }}>
          <div className="field-label">System Prompt</div>
          <textarea
            value={String(draft.prompt.system_prompt ?? "")}
            onChange={(e) => setDraft({ ...draft, prompt: { ...draft.prompt, system_prompt: e.target.value } })}
          />
        </section>
      )}

      {tab === "memory" && (
        <section className="panel" style={{ padding: 16 }}>
          <pre className="field-value">{JSON.stringify(draft.memory ?? {}, null, 2)}</pre>
        </section>
      )}

      {tab === "voice" && (
        <section className="panel" style={{ padding: 16 }}>
          <pre className="field-value">{JSON.stringify(draft.voice ?? { enabled: false }, null, 2)}</pre>
        </section>
      )}

      {tab === "power" && (
        <section className="panel" style={{ padding: 16 }}>
          <p>Restart applies the on-disk config to <code>{draft.identity.service}</code>.</p>
          {draft.meta.id === "sentinel" && (
            <div className="banner">Sentinel is catalogued but <code>schubert-sentinel.service</code> is not active yet.</div>
          )}
          <div className="actions">
            <button className="danger" onClick={onRestart}>Power / Restart</button>
          </div>
        </section>
      )}

      <div className="actions">
        <button className="primary" onClick={onSave}>Apply Changes</button>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  readOnly,
  placeholder,
}: {
  label: string;
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  placeholder?: string;
}) {
  return (
    <div className="row">
      <label className="field-label">{label}</label>
      <input value={value} readOnly={readOnly} placeholder={placeholder} onChange={(e) => onChange?.(e.target.value)} />
    </div>
  );
}
