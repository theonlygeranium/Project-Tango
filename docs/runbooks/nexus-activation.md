# Nexus Fleet Model Activation Runbook

## Prerequisites

- Python 3.14+ (venv at `/opt/Project-Tango/venv/`)
- Redis running on `localhost:6379`
- LiteLLM proxy running on `localhost:4000`
- Discord bot tokens in environment variables (`/opt/Project-Tango/.env`)
- All NX-SPEC-01 through 08 and NX-SPEC-10 implementations complete

## Activation Steps

### 1. Validate manifest

```bash
cd /opt/Project-Tango
/opt/Project-Tango/venv/bin/python -c "
from nexus.manifest import load_manifest
m = load_manifest('fleet-manifest.yaml')
print(f'Manifest v{m.version} with {len(m.bots)} bots')
for bid, bc in m.bots.items():
    print(f'  {bid}: tier={bc.tier}, port={bc.port}, service={bc.systemd_service_name}')
"
```

### 2. Install dependencies

```bash
cd /opt/Project-Tango
/opt/Project-Tango/venv/bin/pip install -e ".[dev]"
```

### 3. Run test suite

```bash
cd /opt/Project-Tango
/opt/Project-Tango/venv/bin/python -m pytest src/nexus/tests/ -v --tb=short
```

All tests must pass before proceeding. The suite includes:
- Unit tests for each module (bus, self-healing, orchestrator, updates, flywheel, testing)
- Integration tests (`test_integration.py`) covering end-to-end flows

### 4. Initialize Nexus Bus

```bash
cd /opt/Project-Tango
/opt/Project-Tango/venv/bin/python -c "
import asyncio
import redis.asyncio as aioredis
from nexus.bus.client import STREAM_MAP

async def init():
    r = aioredis.from_url('redis://localhost:6379/0', decode_responses=True)
    await r.ping()
    for stream in set(STREAM_MAP.values()):
        try:
            await r.xgroup_create(stream, 'nexus-fleet', id='0')
            print(f'Created group on {stream}')
        except Exception as e:
            if 'BUSYGROUP' in str(e):
                print(f'Group already exists on {stream}')
            else:
                raise
    await r.aclose()

asyncio.run(init())
"
```

### 5. Start bot services (in rollout order)

The rollout order is defined in `fleet-manifest.yaml` under `updates.rollout_order`:

```bash
# 1. Cartographer (canary)
sudo -u z121532 systemctl start schubert-cartographer
# Wait 60s, check health
sudo -u z121532 systemctl is-active schubert-cartographer

# 2. Proctor
sudo -u z121532 systemctl start schubert-proctor
# Wait 60s, check health
sudo -u z121532 systemctl is-active schubert-proctor

# 3. Quartermaster
sudo -u z121532 systemctl start schubert-quartermaster
# Wait 60s, check health
sudo -u z121532 systemctl is-active schubert-quartermaster

# 4. Dr. Voss
sudo -u z121532 systemctl start schubert-dr-voss
# Wait 60s, check health
sudo -u z121532 systemctl is-active schubert-dr-voss

# 5. Dr. Cortex
sudo -u z121532 systemctl start schubert-cortex
# Wait 60s, check health
sudo -u z121532 systemctl is-active schubert-cortex

# 6. Architect
sudo -u z121532 systemctl start schubert-architect
# Wait 60s, check health
sudo -u z121532 systemctl is-active schubert-architect

# 7. Admiral (last)
sudo -u z121532 systemctl start schubert-bot
# Wait 60s, check health
sudo -u z121532 systemctl is-active schubert-bot

# 8. Sentinel
sudo -u z121532 systemctl start schubert-sentinel
# Wait 60s, check health
sudo -u z121532 systemctl is-active schubert-sentinel
```

### 6. Verify fleet health

```bash
cd /opt/Project-Tango
/opt/Project-Tango/venv/bin/python -c "
import asyncio
import redis.asyncio as aioredis
from nexus.bus.client import STREAM_MAP

async def check():
    r = aioredis.from_url('redis://localhost:6379/0', decode_responses=True)
    await r.ping()
    # Check for recent health reports
    entries = await r.xrange('nexus:health')
    health_reports = [e for e in entries if e[1].get('event_type') == 'health.report']
    print(f'Health reports: {len(health_reports)}')
    for _, fields in health_reports[-5:]:
        import json
        payload = json.loads(fields['payload'])
        print(f'  {payload[\"bot_id\"]}: {payload[\"status\"]}')
    await r.aclose()

asyncio.run(check())
"
```

Alternatively, use the deployment script for the full sequence:

```bash
cd /opt/Project-Tango
/opt/Project-Tango/venv/bin/python -m scripts.deploy_nexus
```

## Rollback Procedure

If the fleet is unstable after activation:

### 1. Stop all Nexus services

```bash
# Stop in reverse rollout order
sudo -u z121532 systemctl stop schubert-sentinel
sudo -u z121532 systemctl stop schubert-bot
sudo -u z121532 systemctl stop schubert-architect
sudo -u z121532 systemctl stop schubert-cortex
sudo -u z121532 systemctl stop schubert-dr-voss
sudo -u z121532 systemctl stop schubert-quartermaster
sudo -u z121532 systemctl stop schubert-proctor
sudo -u z121532 systemctl stop schubert-cartographer
```

### 2. Restore previous manifest

```bash
cd /opt/Project-Tango
git checkout <previous-stable-commit> -- fleet-manifest.yaml
```

### 3. Clear Nexus Bus state (optional)

```bash
redis-cli FLUSHDB
# Or selectively:
redis-cli DEL nexus:tasks nexus:health nexus:failures nexus:updates nexus:testing nexus:flywheel
```

### 4. Restart services with previous version

```bash
# Re-initialize bus
/opt/Project-Tango/venv/bin/python -c "
import asyncio
import redis.asyncio as aioredis
from nexus.bus.client import STREAM_MAP

async def init():
    r = aioredis.from_url('redis://localhost:6379/0', decode_responses=True)
    for stream in set(STREAM_MAP.values()):
        try:
            await r.xgroup_create(stream, 'nexus-fleet', id='0')
        except Exception:
            pass
    await r.aclose()

asyncio.run(init())
"

# Start services in rollout order (see step 5 above)
```

### 5. Verify rollback

```bash
# Check all services are active
for svc in schubert-cartographer schubert-proctor schubert-quartermaster \
           schubert-dr-voss schubert-cortex schubert-architect schubert-bot \
           schubert-sentinel; do
    echo -n "$svc: "
    sudo -u z121532 systemctl is-active $svc
done
```

## Troubleshooting

### Bot won't start

1. Check journal logs: `sudo journalctl -u <service-name> -n 50 --no-pager`
2. Verify Python path: `/opt/Project-Tango/venv/bin/python --version`
3. Check for crash-loop marker: `ls /tmp/*-crash-loop-marker`
4. If marker exists, remove it: `rm /tmp/<bot-id>-crash-loop-marker`

### Nexus Bus not connecting

1. Verify Redis is running: `redis-cli ping`
2. Check Redis URL in manifest: `grep redis_url fleet-manifest.yaml`
3. Verify consumer groups: `redis-cli XINFO GROUPS nexus:tasks`

### Circuit breaker stuck open

1. Check breaker state via health report events
2. Wait for recovery timeout to elapse (default 30s for LLM)
3. If stuck, restart the bot service to reset breakers

### Sentinel not running tests

1. Check Sentinel service: `sudo -u z121532 systemctl is-active schubert-sentinel`
2. Verify recipes exist: `ls tests/recipes/*.yaml`
3. Check Sentinel logs: `sudo journalctl -u schubert-sentinel -n 50 --no-pager`
4. Manually trigger a test cycle via Nexus Bus event

## Service Summary

| Bot | Service Name | Port | Tier |
|---|---|---|---|
| Admiral | schubert-bot | 8001 | 0 |
| Architect | schubert-architect | 8002 | 1 |
| Dr. Voss | schubert-dr-voss | 8003 | 1 |
| Dr. Cortex | schubert-cortex | 8004 | 1 |
| Quartermaster | schubert-quartermaster | 8005 | 2 |
| Cartographer | schubert-cartographer | 8006 | 2 |
| Proctor | schubert-proctor | 8007 | 3 |
| Sentinel | schubert-sentinel | 8008 | 3 |
