# ── Service registry import for validation ─────────────────────────────────
try:
    from service_registry import validate_service, resolve_service, VALID_SERVICES, list_services
except ImportError:
    validate_service = lambda s: (True, None)
    resolve_service = lambda s: s
    VALID_SERVICES = set()
    list_services = lambda: []