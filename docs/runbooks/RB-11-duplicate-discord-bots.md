# RB-11 — Duplicate Discord bot sessions

## Symptom

A fleet bot (most commonly Architect) replies twice to the same human message,
in tandem, as if two copies of the bot are listening.

## Cause

Two systemd units executed the same script with the same Discord token:

- `architect-bot.service` **and** `schubert-architect.service`
- `proctor-bot.service` **and** `schubert-proctor.service`

Discord delivers every message to every gateway session for that token.

## Immediate check

```bash
ps -eo pid,cmd | grep -E 'architect-bot.py|proctor-bot.py' | grep -v grep
systemctl is-active schubert-architect.service architect-bot.service
systemctl is-enabled architect-bot.service   # should be: masked
```

There must be **one** process per bot script.

## Fix (already applied 2026-08-22)

1. Stop and mask the legacy units.
2. Keep the `schubert-*` units (Cortex exception: `cortex-bot.service`).
3. Process flock in `scripts/singleton_lock.py` so a second copy exits 0.

## Do not

- `systemctl unmask architect-bot.service`
- Start both `architect-bot` and `schubert-architect`
- Enable `schubert-cortex.service` (it pointed at the stub `cortex-bot.py`)
