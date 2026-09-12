# Project Tango — Stable Baseline & Rollback Guide

## ✅ Stable Baseline: `v2.0-stable`

| Field | Value |
|---|---|
| **Tag** | `v2.0-stable` |
| **Commit** | `ec52a40` |
| **Date** | September 11, 2026 |
| **Branch** | `main` |

This is the second stable release of Project Tango. It builds on the v1.0-stable
baseline with the v2 Voice Pipeline Optimization (DeepGram Flux Eager End-of-Turn),
ElevenLabs verification tooling, per-agent-turn latency logging, and conditional
`use_pvc_as_ivc` support. All features are confirmed operational and running in
production on Schubert.

---

## What's New in v2.0-stable

- **DeepGram Flux Eager End-of-Turn** (`eager_eot_threshold`) — per-persona tunable
  for English personas (Chris 0.6, Jeremiah 0.6, Jeremiah V2 0.55, Jacob 0.65),
  disabled for therapy, meditation, and Tagalog personas. Cuts hundreds of
  milliseconds from end-to-end response time. See ADR-011.
- **Global eager EOT override** — `TANGO_EAGER_EOT_THRESHOLD` env var (range 0.3–0.9)
  supersedes per-persona values when set.
- **ElevenLabs voice clone audit script** — `scripts/audit_elevenlabs_voices.py`
  classifies all 8 voice IDs as premade/IVC/PVC.
- **ElevenLabs TTFB verification script** — `scripts/verify_elevenlabs_ttfb.py`
  measures time-to-first-byte on the US endpoint (5-iteration test).
- **Per-agent-turn latency logging** — `tango-backend` logs `latency_ms` for
  every agent turn.
- **Conditional `use_pvc_as_ivc` support** — `TANGO_ELEVENLABS_USE_PVC_AS_IVC`
  env var with graceful fallback when the installed plugin version doesn't support it.

---

## ✅ Previous Baseline: `v1.0-stable`

| Field | Value |
|---|---|
| **Tag** | `v1.0-stable` |
| **Commit** | `fdc9144` |
| **Date** | June 28, 2026 |
| **Branch** | `main` |

This was the first fully verified, human-tested stable release of Project Tango.

---

## What's Confirmed Working at v2.0-stable

- **All 8 personas** operational: Damian, Chris, Jeremiah, Jeremiah V2, Jacob, Mama Lulu, Nathaniel, Tita Baby
- **Eager End-of-Turn** — per-persona thresholds active for conversational English personas
- **LiveKit agent dispatch** — agents join rooms correctly after user connects
- **Deepgram Flux STT** (`flux-general-en`) for all English personas with native end-of-turn detection and eager EOT
- **Deepgram Nova-3 STT** (`language="tl"`, `smart_format=True`) for Tita Baby and Mama Lulu — correct Tagalog/Taglish spelling and comprehension
- **ElevenLabs Flash v2.5 TTS** with US geographic routing and per-persona voice settings
- **Deepgram Aura TTS fallback** — auto-activates when primary TTS fails (billing, rate limit, stopped sidecar)
- **Audio TurnDetector** — LiveKit's `inference.TurnDetector()` replaces STT-based turn detection, eliminates VAD/STT race conditions
- **Mid-speech pauses resolved** — `use_tts_aligned_transcript=False` prevents `_SegmentSynchronizerImpl` race conditions
- **Conversation history** — PostgreSQL 18 session/turn recording with orphan-session guard
- **Account authentication** — Argon2id password verification, opaque database sessions, CSRF defense, admin dashboard
- **Persona switching** — `clearConnectionDetails` prevents stale tokens between sessions
- **Mobile/iOS optimization** — viewport-fit=cover, PWA manifest, two-column persona grid, touch support
- **CI/CD** — GitHub Actions `deploy.yml` (workflow_dispatch) with Tailscale SSH to Schubert
- **Infrastructure** — Cloudflare tunnel routing, Caddy, Ollama (qwen3), LiteLLM proxy all verified active
- **Tango Health Guardian** — six-layer self-healing monitor (systemd timer, every 3 min) with Discord webhook alerts
- **Discord bots** — Admiral Schubert (Level 3 autonomous agent), Tango Bot, Dr. Cortex — all with fleet-config externalization

---

## How to Revert to This Baseline

### On Schubert (production)

```bash
# SSH into Schubert as z121532
cd /opt/Project-Tango

# Fetch latest tags
git fetch --tags

# Hard reset to the stable tag
git checkout v2.0-stable

# Rebuild frontend
cd frontend
npm run build
cp -r .next/static .next/standalone/.next/static
cp -r public .next/standalone/public

# Restart services
sudo systemctl restart tango-backend tango-web

# Verify
systemctl is-active tango-backend tango-web
curl -s https://tango-api.schubert.life/healthz
```

### Revert to v1.0-stable (if v2 causes issues)

```bash
cd /opt/Project-Tango
git checkout v1.0-stable
cd frontend && npm run build
cp -r .next/static .next/standalone/.next/static
cp -r public .next/standalone/public
sudo systemctl restart tango-backend tango-web
systemctl is-active tango-backend tango-web
curl -s https://tango-api.schubert.life/healthz
```

### Via Git (local or Codex)

```bash
# Check out the stable tag
git checkout v2.0-stable

# Or reset main to this commit (destructive — use with care)
git checkout main
git reset --hard ec52a40
git push origin main --force
```

### Via GitHub UI

1. Go to **Releases** → `v2.0-stable`
2. Click **Compare** to see what changed since this baseline
3. To restore: download the source zip/tarball from the release and redeploy manually

---

## Before Adding New Features

1. **Branch from `main`** — never develop directly on `main`
2. **Test on Schubert** before merging
3. **Tag new stable versions** as `v2.1-stable`, `v2.2-stable`, etc. when verified
4. **If anything breaks**, revert Schubert to `v2.0-stable` (or `v1.0-stable`) using the commands above while you debug

---

## Key Technical Decisions at This Baseline

| Decision | Rationale |
|---|---|
| Flux (`flux-general-en`) for English | Native EOT detection, lowest latency |
| Eager EOT per-persona thresholds | Cuts hundreds of ms from response time; disabled for therapy/meditation/Tagalog (ADR-011) |
| Nova-3 `language="tl"` for Tita Baby & Mama Lulu | Flux Multilingual does not support Tagalog; Nova-3 monolingual `tl` provides correct orthography |
| `use_tts_aligned_transcript=False` | Do not feed ElevenLabs word timings into the transcription node (ADR-004) |
| `sync_transcription=False` | Do not construct RoomIO `_SegmentSynchronizerImpl`; required to prevent late-session cutouts (ADR-012) |
| `max_tool_steps=8` | Tool-heavy wiki/docs/MCP turns finish before `tool_choice='none'` (ADR-012) |
| Audio TurnDetector (`inference.TurnDetector()`) | Replaces STT-based turn detection; eliminates VAD/STT race conditions |
| Cloudflare tunnel direct to `localhost:3006`/`localhost:8030` | Bypasses Caddy to prevent Error 522 and duplicate CORS headers |
| Agent dispatch via POST `/api/dispatch` after `room.connect()` | Prevents agent timeout before user clicks Start |
| Deepgram Aura TTS fallback | Prevents total voice silence when ElevenLabs or F5-TTS fails |
| Account authentication (Argon2id) | Secure password-only accounts with CSRF defense and session management |

---

*Last updated: September 11, 2026 — EdStratum Labs / Project Tango*
