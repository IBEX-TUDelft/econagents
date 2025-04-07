"""
Configuration parsers for different server types.

This package provides configuration parsers for different server types:
- Base: No custom event handlers
- Basic: Custom event handler for player-is-ready messages
- IBEX-TUDelft: Handles player-is-ready messages and role assignment
"""

from econagents.config_parser.base import BaseConfigParser
from econagents.config_parser.basic import BasicConfigParser
from econagents.config_parser.ibex_tudelft import IbexTudelftConfigParser

__all__ = [
    "BaseConfigParser",
    "BasicConfigParser",
    "IbexTudelftConfigParser",
]
