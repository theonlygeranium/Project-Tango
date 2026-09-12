# Legacy duplicate systemd units

These unit files were moved out of `/etc/systemd/system/` on 2026-08-22
because they launched a second copy of the same Discord bot.

| File | Duplicate of | Symptom |
|---|---|---|
| `architect-bot.service.disabled` | `schubert-architect.service` | Architect answered twice |
| `proctor-bot.service.disabled` | `schubert-proctor.service` | Two Proctor gateway sessions |
| `schubert-cortex.service.disabled` | `cortex-bot.service` | Wrong script (`cortex-bot.py` stub) |

Canonical units:

- Admiral: `schubert-bot.service` -> `scripts/schubert-bot-v2.py`
- Architect: `schubert-architect.service` -> `scripts/architect-bot.py`
- Proctor: `schubert-proctor.service` -> `scripts/proctor-bot.py`
- Dr. Voss: `schubert-dr-voss.service`
- Quartermaster: `schubert-quartermaster.service`
- Cartographer: `schubert-cartographer.service`
- Dr. Cortex: `cortex-bot.service` -> `scripts/dr-cortex-bot.py`

The old names are **masked** (`/dev/null`) so `systemctl start architect-bot` cannot
bring a second session back. `scripts/service_registry.py` aliases those names to
the canonical units. Each bot also takes a process-level flock via
`scripts/singleton_lock.py`.

Do not unmask or restore these files.
