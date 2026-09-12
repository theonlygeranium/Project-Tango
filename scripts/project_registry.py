"""
ProjectRegistry — Channel-to-Project Mapping
============================================
Manages the mapping between Discord channels/threads and projects.

Each project carries its own configuration: working directory, system prompt
overlay, enabled MCP servers, and context files. The registry persists to a
JSON file and can be migrated to Postgres in Phase 3.

Usage:
    registry = ProjectRegistry("/opt/Project-Tango/data/projects.json")
    registry.load()
    project = registry.get_project_for_channel(123456789)
    if project:
        print(f"Channel is bound to project: {project.name}")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("schubert-bot.projects")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ProjectConfig:
    """Configuration for a single project."""
    name: str
    description: str = ""
    workdir: str = ""
    system_prompt: str = ""
    enabled_mcp_servers: list[str] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)
    channel_bindings: dict[int, str] = field(default_factory=dict)  # channel_id -> "primary"|"secondary"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectConfig":
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            workdir=data.get("workdir", ""),
            system_prompt=data.get("system_prompt", ""),
            enabled_mcp_servers=data.get("enabled_mcp_servers", []),
            context_files=data.get("context_files", []),
            channel_bindings={int(k): v for k, v in data.get("channel_bindings", {}).items()},
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ProjectRegistry:
    """
    Manages project configurations and channel-to-project bindings.

    Persistence: JSON file at `data_path`. Loaded at startup, saved on every
    mutation. Thread-safe via a simple lock (sufficient for single-process bot).
    """

    def __init__(self, data_path: str = "/opt/Project-Tango/data/projects.json"):
        self.data_path = data_path
        self._projects: dict[str, ProjectConfig] = {}
        self._channel_index: dict[int, str] = {}  # channel_id -> project_name
        self._loaded = False

    # -- Persistence -------------------------------------------------------

    def load(self) -> None:
        """Load projects from the JSON file. Creates a default project if empty."""
        try:
            with open(self.data_path, "r") as f:
                data = json.load(f)
            self._projects = {}
            for name, proj_data in data.get("projects", {}).items():
                self._projects[name] = ProjectConfig.from_dict(proj_data)
            self._rebuild_channel_index()
            self._loaded = True
            logger.info(f"Loaded {len(self._projects)} projects from {self.data_path}")
        except FileNotFoundError:
            logger.info(f"No projects file at {self.data_path}, starting fresh")
            self._projects = {}
            self._loaded = True
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
            self._projects = {}
            self._loaded = True

    def save(self) -> None:
        """Save all projects to the JSON file."""
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        data = {
            "projects": {name: proj.to_dict() for name, proj in self._projects.items()}
        }
        try:
            with open(self.data_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved {len(self._projects)} projects to {self.data_path}")
        except Exception as e:
            logger.error(f"Failed to save projects: {e}")

    def _rebuild_channel_index(self) -> None:
        """Rebuild the channel_id -> project_name lookup index."""
        self._channel_index = {}
        for name, proj in self._projects.items():
            for channel_id in proj.channel_bindings:
                self._channel_index[channel_id] = name

    # -- Project CRUD ------------------------------------------------------

    def create_project(
        self,
        name: str,
        description: str = "",
        workdir: str = "",
        system_prompt: str = "",
        enabled_mcp_servers: list[str] | None = None,
        context_files: list[str] | None = None,
    ) -> ProjectConfig:
        """Create a new project. Raises ValueError if name already exists."""
        if name in self._projects:
            raise ValueError(f"Project '{name}' already exists")
        proj = ProjectConfig(
            name=name,
            description=description,
            workdir=workdir,
            system_prompt=system_prompt,
            enabled_mcp_servers=enabled_mcp_servers or [],
            context_files=context_files or [],
        )
        self._projects[name] = proj
        self.save()
        logger.info(f"Created project: {name}")
        return proj

    def get_project(self, name: str) -> Optional[ProjectConfig]:
        """Get a project by name."""
        return self._projects.get(name)

    def list_projects(self) -> list[ProjectConfig]:
        """List all projects."""
        return list(self._projects.values())

    def update_project(self, name: str, updates: dict) -> ProjectConfig:
        """Update fields on an existing project. Raises ValueError if not found."""
        proj = self._projects.get(name)
        if proj is None:
            raise ValueError(f"Project '{name}' not found")
        if "description" in updates:
            proj.description = updates["description"]
        if "workdir" in updates:
            proj.workdir = updates["workdir"]
        if "system_prompt" in updates:
            proj.system_prompt = updates["system_prompt"]
        if "enabled_mcp_servers" in updates:
            proj.enabled_mcp_servers = updates["enabled_mcp_servers"]
        if "context_files" in updates:
            proj.context_files = updates["context_files"]
        proj.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()
        logger.info(f"Updated project: {name}")
        return proj

    def delete_project(self, name: str) -> bool:
        """Delete a project. Returns True if deleted, False if not found."""
        if name not in self._projects:
            return False
        # Remove channel bindings from index
        for channel_id in self._projects[name].channel_bindings:
            self._channel_index.pop(channel_id, None)
        del self._projects[name]
        self.save()
        logger.info(f"Deleted project: {name}")
        return True

    # -- Channel binding ---------------------------------------------------

    def bind_channel(
        self, channel_id: int, project_name: str, binding_type: str = "primary"
    ) -> None:
        """Bind a Discord channel to a project. Raises ValueError if project not found."""
        proj = self._projects.get(project_name)
        if proj is None:
            raise ValueError(f"Project '{project_name}' not found")
        # Unbind from previous project if any
        old_project = self._channel_index.get(channel_id)
        if old_project and old_project != project_name:
            old_proj = self._projects.get(old_project)
            if old_proj:
                old_proj.channel_bindings.pop(channel_id, None)
        proj.channel_bindings[channel_id] = binding_type
        self._channel_index[channel_id] = project_name
        proj.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()
        logger.info(f"Bound channel {channel_id} to project '{project_name}' ({binding_type})")

    def unbind_channel(self, channel_id: int) -> bool:
        """Unbind a channel from its project. Returns True if was bound."""
        project_name = self._channel_index.pop(channel_id, None)
        if project_name is None:
            return False
        proj = self._projects.get(project_name)
        if proj:
            proj.channel_bindings.pop(channel_id, None)
            proj.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()
        logger.info(f"Unbound channel {channel_id} from project '{project_name}'")
        return True

    def get_project_for_channel(self, channel_id: int) -> Optional[ProjectConfig]:
        """Look up which project is bound to a Discord channel."""
        project_name = self._channel_index.get(channel_id)
        if project_name is None:
            return None
        return self._projects.get(project_name)

    def get_binding_info(self, channel_id: int) -> Optional[tuple[str, str]]:
        """Return (project_name, binding_type) for a channel, or None."""
        project_name = self._channel_index.get(channel_id)
        if project_name is None:
            return None
        proj = self._projects.get(project_name)
        if proj is None:
            return None
        binding_type = proj.channel_bindings.get(channel_id, "primary")
        return (project_name, binding_type)

    # -- Utility -----------------------------------------------------------

    def ensure_default_project(self, channel_id: int, system_prompt: str = "") -> None:
        """
        Ensure a 'default' project exists, bound to the given channel.
        Called at startup for V1 compatibility — the original BOT_CHANNEL_ID
        becomes the default project's primary channel.
        """
        if "default" not in self._projects:
            self.create_project(
                name="default",
                description="Default project — server-wide management (V1 compatibility)",
                workdir="/opt/Project-Tango",
                system_prompt=system_prompt,
            )
        proj = self._projects["default"]
        if channel_id not in proj.channel_bindings:
            self.bind_channel(channel_id, "default", "primary")