from pathlib import Path
from typing import Any, Optional

import yaml


class GameConfigurationManager:
    """
    Loads, saves, and validates YAML game configuration files.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        """Initialize the configuration manager."""
        self.config = config or {}

    def from_yaml(self, path: str) -> dict[str, Any]:
        """Load config from a YAML file."""
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with path_obj.open(encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        return self.config

    def to_yaml(self, path: str) -> None:
        """Export current config to a YAML file."""
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        with path_obj.open("w", encoding="utf-8") as f:
            yaml.dump(self.config, f, default_flow_style=False)

    def define_rules(self, **kwargs: Any) -> None:
        """Programmatically define or update parts of the game config."""
        for key, value in kwargs.items():
            self.config[key] = value

    def get_config(self) -> dict[str, Any]:
        """Get the current configuration."""
        return self.config.copy()

    def validate(self) -> bool:
        """Validate the current configuration."""
        required_fields = ["name", "phases", "roles"]
        return all(field in self.config for field in required_fields)
