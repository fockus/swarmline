"""YAML command definitions loader.

Загружает определения команд из YAML файлов для auto-discovery.
"""

from __future__ import annotations

from typing import Any

import yaml


def load_commands_from_yaml(path: str) -> list[dict[str, Any]]:
    """Загрузить определения команд из YAML файла.

    Формат YAML:
        commands:
          - name: deploy.staging
            description: Deploy to staging
            category: admin
            parameters:
              type: object
              properties:
                version:
                  type: string

    Returns:
        Список dict с полями name, description, category, parameters.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "commands" not in data:
        return []

    commands: list[dict[str, Any]] = []
    for cmd_def in data["commands"]:
        if not isinstance(cmd_def, dict) or "name" not in cmd_def:
            continue
        commands.append({
            "name": cmd_def["name"],
            "description": cmd_def.get("description", ""),
            "category": cmd_def.get("category", ""),
            "parameters": cmd_def.get("parameters"),
        })

    return commands
