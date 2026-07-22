from __future__ import annotations

import uuid

import pytest

import accounts
from personas import ALLOWED_LLM_MODELS, TANGO_PERSONAS


class PolicyPool:
    def __init__(self, row: dict | None) -> None:
        self.row = row
        self.calls: list[tuple] = []

    async def fetchrow(self, query: str, *args):
        self.calls.append((query, args))
        return self.row


def test_persona_access_rejects_unknown_duplicate_and_unapproved_models() -> None:
    with pytest.raises(ValueError, match="Unknown persona"):
        accounts.validate_persona_access([{"persona_id": "unknown"}])
    with pytest.raises(ValueError, match="Duplicate persona"):
        accounts.validate_persona_access(
            [{"persona_id": "therapy"}, {"persona_id": "therapy"}]
        )
    with pytest.raises(ValueError, match="Unsupported LLM model"):
        accounts.validate_persona_access(
            [{"persona_id": "therapy", "llm_model_override": "ollama/direct"}]
        )


def test_persona_access_accepts_every_source_controlled_model() -> None:
    model = next(iter(ALLOWED_LLM_MODELS))
    result = accounts.validate_persona_access(
        [{"persona_id": "therapy", "llm_model_override": model}]
    )
    assert result == [{"persona_id": "therapy", "llm_model_override": model}]


@pytest.mark.asyncio
async def test_regular_policy_requires_access_and_ignores_client_model() -> None:
    user_id = uuid.uuid4()
    denied = await accounts.resolve_persona_policy(
        PolicyPool(None),
        user_id=user_id,
        role="regular",
        persona_id="therapy",
        requested_model="writer/palmyra-x5-voice",
    )
    assert denied is None

    pool = PolicyPool({"llm_model_override": None})
    persona, effective = await accounts.resolve_persona_policy(
        pool,
        user_id=user_id,
        role="regular",
        persona_id="therapy",
        requested_model="writer/palmyra-x5-voice",
    )
    assert effective == persona.llm_model


@pytest.mark.asyncio
async def test_admin_policy_accepts_only_allowlisted_override() -> None:
    pool = PolicyPool(None)
    persona, effective = await accounts.resolve_persona_policy(
        pool,
        user_id=uuid.uuid4(),
        role="admin",
        persona_id="therapy",
        requested_model="writer/palmyra-x5-voice",
    )
    assert effective == "writer/palmyra-x5-voice"
    assert not pool.calls

    _, fallback = await accounts.resolve_persona_policy(
        pool,
        user_id=uuid.uuid4(),
        role="admin",
        persona_id="therapy",
        requested_model="ollama/qwen3.6:latest",
    )
    assert fallback == persona.llm_model


@pytest.mark.asyncio
async def test_audit_log_rejects_secret_metadata() -> None:
    with pytest.raises(ValueError, match="Secrets"):
        await accounts.audit_admin_action(
            object(),
            actor_user_id=uuid.uuid4(),
            target_user_id=uuid.uuid4(),
            action="bad",
            metadata={"password": "never-log-this"},
        )


def test_catalog_has_no_direct_ollama_model() -> None:
    assert TANGO_PERSONAS
    assert all(not model.startswith("ollama/") for model in ALLOWED_LLM_MODELS)
