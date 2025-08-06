"""
Configuration parsers for different server types.

This package provides configuration parsers for different server types:
- Base: No custom event handlers
- Basic: Custom event handler for player-is-ready messages
"""

from econagents.config_parser.base import BaseConfigParser
from econagents.config_parser.basic import BasicConfigParser

__all__ = [
    "BaseConfigParser",
    "BasicConfigParser",
]
