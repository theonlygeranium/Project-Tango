# Project Tango — Stable Baseline & Rollback Guide

## ✅ Stable Baseline: `v1.0-stable`

| Field | Value |
|---|---|
| **Tag** | `v1.0-stable` |
| **Commit** | `fdc9144` |
| **Date** | June 28, 2026 |
| **Branch** | `main` |

This is the first fully verified, human-tested stable release of Project Tango. All major features are confirmed operational and all known critical bugs have been resolved.

---

## What's Confirmed Working at This Baseline

- **All 7 personas** operational: Damian, Chris, Jeremiah, Jacob, Mama Lulu, Nathaniel, Tita Baby
- **LiveKit agent dispatch** — agents join rooms correctly after user connects
- **Deepgram Flux STT** (`flux-general-en`) for all English personas with native end-of-turn detection
- **Deepgram Nova-3 STT** (`language="tl"`, `smart_format=True`) for Tita Baby and Mama Lulu — correct Tagalog/Taglish spelling and comprehension
- **ElevenLabs Flash v2.5 TTS** with US geographic routing and per-persona voice settings
- **Mid-speech pauses resolved** — `use_tts_aligned_transcript=False` prevents `_SegmentSynchronizerImpl` race conditions
- **Turn detection** — `turn_detection="stt"` correctly nested in `turn_handling` dict (LiveKit v2.0 compliant)
- **Conversation history** — PostgreSQL 18 session/turn recording with orphan-session guard
- **Persona switching** — `clearConnectionDetails` prevents stale tokens between sessions
- **Mobile/iOS optimization** — viewport-fit=cover, PWA manifest, two-column persona grid, touch support
- **CI/CD** — GitHub Actions `deploy.yml` (workflow_dispatch) with Tailscale SSH to Schubert
- **Infrastructure** — Cloudflare tunnel routing, Caddy, Ollama (qwen3), LiteLLM proxy all verified active

---

## How to Revert to This Baseline

### On Schubert (production)

```bash
# SSH into Schubert as z121532
cd /opt/Project-Tango

# Fetch latest tags
git fetch --tags

# Hard reset to the stable tag
git checkout v1.0-stable

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

### Via Git (local or Codex)

```bash
# Check out the stable tag
git checkout v1.0-stable

# Or reset main to this commit (destructive — use with care)
git checkout main
git reset --hard fdc9144
git push origin main --force
```

### Via GitHub UI

1. Go to **Releases** → `v1.0-stable`
2. Click **Compare** to see what changed since this baseline
3. To restore: download the source zip/tarball from the release and redeploy manually

---

## Before Adding New Features

1. **Branch from `main`** — never develop directly on `main`
2. **Test on Schubert** before merging
3. **Tag new stable versions** as `v1.1-stable`, `v1.2-stable`, etc. when verified
4. **If anything breaks**, revert Schubert to `v1.0-stable` using the commands above while you debug

---

## Key Technical Decisions at This Baseline

| Decision | Rationale |
|---|---|
| Flux (`flux-general-en`) for English | Native EOT detection, lowest latency |
| Nova-3 `language="tl"` for Tita Baby & Mama Lulu | Flux Multilingual does not support Tagalog; Nova-3 monolingual `tl` provides correct orthography |
| `use_tts_aligned_transcript=False` | Prevents `_SegmentSynchronizerImpl` race condition mid-speech pauses with ElevenLabs |
| `turn_detection="stt"` inside `turn_handling` dict | LiveKit Agents v2.0 API compliance |
| Cloudflare tunnel direct to `localhost:3006`/`localhost:8030` | Bypasses Caddy to prevent Error 522 and duplicate CORS headers |
| Agent dispatch via POST `/api/dispatch` after `room.connect()` | Prevents agent timeout before user clicks Start |

---

*Last updated: June 28, 2026 — Geronimo AI / Project Tango*