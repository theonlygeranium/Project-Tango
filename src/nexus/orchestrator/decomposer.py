"""Task decomposition and routing table for the Orchestrator Router.

The TaskDecomposer uses the LLM (writer/palmyra-x6) to parse an incoming
request into sub-tasks. Each sub-task carries a domain that maps to a
target bot via the RoutingTable. Multi-domain requests produce multiple
sub-tasks.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from nexus.bus.client import NexusBus
from nexus.manifest.schema import FleetManifest

logger = logging.getLogger(__name__)


class RoutingTable:
    """Maps domain strings to target bot names.

    The routing table is loaded from the fleet manifest's ``routing_table``
    section. The special value ``"decompose"`` indicates that a domain is
    multi-domain and must be decomposed further before routing.
    """

    def __init__(self, entries: dict[str, str]) -> None:
        self._entries: dict[str, str] = dict(entries)
        logger.debug("RoutingTable initialized with %d entries", len(self._entries))

    def resolve(self, domain: str) -> str:
        """Return the target bot for *domain*.

        Args:
            domain: One of the routing table keys.

        Returns:
            The target bot name.

        Raises:
            KeyError: If *domain* is not in the routing table.
            ValueError: If *domain* resolves to ``"decompose"`` — multi-domain
                requests must be decomposed into concrete sub-domains first.
        """
        if domain not in self._entries:
            raise KeyError(f"Unknown domain: {domain!r}")
        target = self._entries[domain]
        if target == "decompose":
            raise ValueError(
                f"Domain {domain!r} maps to 'decompose' — "
                "multi-domain requests must be decomposed into concrete sub-tasks first"
            )
        return target

    @property
    def domains(self) -> list[str]:
        """Return a sorted list of all known domain keys."""
        return sorted(self._entries.keys())

    def __contains__(self, domain: str) -> bool:
        return domain in self._entries

    def __len__(self) -> int:
        return len(self._entries)


class TaskDecomposer:
    """Decomposes an incoming request into a list of SubTask objects.

    Uses the LLM (writer/palmyra-x6) to parse the request. The LLM is
    instructed to return JSON: a list of objects with ``subtask_id``,
    ``domain``, ``description``, ``priority``, ``context``, and
    ``acceptance_criteria``. The ``domain`` must be one of the routing
    table keys.
    """

    def __init__(self, nexus: NexusBus, manifest: FleetManifest) -> None:
        self._nexus = nexus
        self._manifest = manifest
        rt_entries = manifest.routing_table or {}
        self._routing_table = RoutingTable(rt_entries)
        logger.debug("TaskDecomposer initialized with routing table: %s", rt_entries)

    @property
    def routing_table(self) -> RoutingTable:
        return self._routing_table

    async def decompose(self, request: str) -> list[Any]:
        """Decompose *request* into a list of SubTask objects.

        If the LLM call fails or returns unparseable output, a single
        fallback SubTask is created with domain ``"multi_domain"`` which
        the routing table maps to ``"decompose"`` — the caller is expected
        to handle that.
        """
        from nexus.orchestrator.router import SubTask

        try:
            raw_plan = await self._llm_decompose(request)
        except Exception as exc:
            logger.error("LLM decomposition failed: %s", exc)
            return [
                SubTask(
                    subtask_id=str(uuid4()),
                    target_bot="decompose",
                    description=request,
                    priority="normal",
                    context={"fallback": True},
                    acceptance_criteria="Request handled",
                )
            ]

        subtasks: list[Any] = []
        for item in raw_plan:
            domain = item.get("domain", "")
            try:
                target_bot = self._routing_table.resolve(domain)
            except KeyError:
                logger.warning("Unknown domain %r in decomposition, skipping", domain)
                continue
            except ValueError:
                # multi_domain — should not appear in a well-formed plan
                logger.warning("Domain %r is multi-domain, skipping", domain)
                continue

            subtask = SubTask(
                subtask_id=item.get("subtask_id", str(uuid4())),
                target_bot=target_bot,
                description=item.get("description", ""),
                priority=item.get("priority", "normal"),
                context=item.get("context", {}),
                acceptance_criteria=item.get("acceptance_criteria", ""),
            )
            subtasks.append(subtask)

        if not subtasks:
            logger.warning("Decomposition produced no sub-tasks for: %s", request[:100])

        return subtasks

    async def _llm_decompose(self, request: str) -> list[dict[str, Any]]:
        """Call the LLM to decompose *request* into a raw plan.

        Returns a list of dicts with keys: subtask_id, domain, description,
        priority, context, acceptance_criteria.
        """
        prompt = self._build_decomposition_prompt(request)
        # The actual LLM call would go through LLMClient, but we keep this
        # lightweight and testable. In production, this would call
        # litellm.acompletion via the LiteLLM proxy at localhost:4000.
        # For now, we use a simple heuristic fallback that inspects the
        # request for known domain keywords.
        return self._heuristic_decompose(request)

    def _build_decomposition_prompt(self, request: str) -> str:
        """Build the LLM prompt for decomposition.

        The prompt instructs the LLM to return JSON: a list of objects with
        subtask_id, domain, description, priority, context, acceptance_criteria.
        Domain must be one of the routing table keys.
        """
        domains = self._routing_table.domains
        return (
            "You are the Admiral Schubert orchestrator. Decompose the following "
            "request into sub-tasks for the Nexus Fleet.\n\n"
            f"Available domains (routing table keys): {', '.join(domains)}\n\n"
            "Return a JSON array. Each element must have:\n"
            '  "subtask_id": a unique string identifier\n'
            '  "domain": one of the available domains\n'
            '  "description": what the bot should do\n'
            '  "priority": "low" | "normal" | "high" | "critical"\n'
            '  "context": an object with any additional context\n'
            '  "acceptance_criteria": how to verify the task is done\n\n'
            f"Request: {request}\n\n"
            "Return ONLY the JSON array, no other text."
        )

    def _parse_plan(self, response: str) -> list[dict[str, Any]]:
        """Parse the LLM response string into a list of dicts.

        Expects a JSON array. Falls back to an empty list on parse failure.
        """
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse LLM response as JSON: %s", exc)
            return []
        if not isinstance(parsed, list):
            logger.error("LLM response is not a JSON array: %s", type(parsed).__name__)
            return []
        return parsed

    def _heuristic_decompose(self, request: str) -> list[dict[str, Any]]:
        """Heuristic decomposition for when the LLM is unavailable.

        Scans the request for known domain keywords and produces sub-tasks
        for each matching domain.
        """
        request_lower = request.lower()
        domain_keywords: dict[str, list[str]] = {
            "infrastructure": ["infrastructure", "server", "system", "hardware"],
            "deployment": ["deploy", "deployment", "rollout", "release"],
            "diagnostics": ["diagnose", "diagnostic", "debug", "troubleshoot"],
            "health": ["health", "healthcheck", "status check", "uptime"],
            "analysis": ["analyze", "analysis", "review", "assess"],
            "patterns": ["pattern", "trend", "benchmark", "compare"],
            "resources": ["resource", "capacity", "allocation", "provision"],
            "inventory": ["inventory", "stock", "supply", "catalog"],
            "documentation": ["document", "documentation", "wiki", "readme"],
            "mapping": ["map", "mapping", "diagram", "topology"],
            "compliance": ["compliance", "audit", "regulation", "policy"],
            "monitoring": ["monitor", "monitoring", "alert", "metric"],
        }

        matched: list[dict[str, Any]] = []
        for domain, keywords in domain_keywords.items():
            if any(kw in request_lower for kw in keywords):
                matched.append(
                    {
                        "subtask_id": str(uuid4()),
                        "domain": domain,
                        "description": request,
                        "priority": "normal",
                        "context": {"source": "heuristic"},
                        "acceptance_criteria": "Task completed successfully",
                    }
                )

        if not matched:
            # Default to multi_domain if nothing matched
            matched.append(
                {
                    "subtask_id": str(uuid4()),
                    "domain": "multi_domain",
                    "description": request,
                    "priority": "normal",
                    "context": {"source": "heuristic_fallback"},
                    "acceptance_criteria": "Request handled",
                }
            )

        return matched
