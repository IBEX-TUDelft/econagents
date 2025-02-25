import json
import logging
from typing import Any, Callable, Dict, List, Optional

import websockets

from econagents.core.events import Message
from econagents.llm.openai import ChatOpenAI


class AgentManager:
    def __init__(
        self,
        url: str,
        login_payload: dict[str, Any],
        game_id: int,
        logger: logging.Logger,
        llm: ChatOpenAI = ChatOpenAI(),
    ):
        self.llm = llm
        self.logger = logger
        self.url = url
        self.ws = None
        self.task = None
        self.running = False
        self.login_payload = login_payload
        self.game_id = game_id
        # Dictionary to store event handlers: {event_type: handler_function}
        self._event_handlers: Dict[str, List[Callable[[Message], Any]]] = {}
        # Handler for all events (will be called for every event)
        self._global_event_handlers: List[Callable[[Message], Any]] = []

        # Pre and post event hooks
        # For specific events: {event_type: [hook_functions]}
        self._pre_event_hooks: Dict[str, List[Callable[[Message], Any]]] = {}
        self._post_event_hooks: Dict[str, List[Callable[[Message], Any]]] = {}
        # For all events
        self._global_pre_event_hooks: List[Callable[[Message], Any]] = []
        self._global_post_event_hooks: List[Callable[[Message], Any]] = []

    def _extract_message_data(self, message: str) -> Optional[Message]:
        try:
            msg = json.loads(message)
            msg_type = msg.get("type", "")
            event_type = msg.get("eventType", "")
            data = msg.get("data", {})
        except json.JSONDecodeError:
            self.logger.error("Invalid JSON received.")
            return None
        return Message(msg_type=msg_type, event_type=event_type, data=data)

    async def on_message(self, message: Message):
        """
        Default implementation to handle incoming messages from the server.

        For event-type messages, routes them to on_event.
        Subclasses can override this method for custom handling.
        """
        self.logger.debug(f"<-- Received message: {message}")
        if message.msg_type == "event":
            await self.on_event(message)

    async def on_event(self, message: Message):
        """
        Handle event messages by routing to specific handlers.

        The execution flow is:
        1. Global pre-event hooks
        2. Event-specific pre-event hooks
        3. Global event handlers
        4. Event-specific handlers
        5. Event-specific post-event hooks
        6. Global post-event hooks

        Subclasses can override this method for custom event handling.
        """
        event_type = message.event_type
        has_specific_handlers = event_type in self._event_handlers

        # Execute global pre-event hooks
        await self._execute_hooks(self._global_pre_event_hooks, message, "global pre-event")

        # Execute specific pre-event hooks if they exist
        if event_type in self._pre_event_hooks:
            await self._execute_hooks(self._pre_event_hooks[event_type], message, f"{event_type} pre-event")

        # Call global event handlers
        await self._execute_hooks(self._global_event_handlers, message, "global event")

        # Call specific event handlers if they exist
        if has_specific_handlers:
            await self._execute_hooks(self._event_handlers[event_type], message, f"{event_type} event")

        # Execute specific post-event hooks if they exist
        if event_type in self._post_event_hooks:
            await self._execute_hooks(self._post_event_hooks[event_type], message, f"{event_type} post-event")

        # Execute global post-event hooks
        await self._execute_hooks(self._global_post_event_hooks, message, "global post-event")

    async def _execute_hooks(self, hooks: List[Callable], message: Message, hook_type: str) -> None:
        """Execute a list of hooks/handlers with proper error handling."""
        for hook in hooks:
            try:
                await self._call_handler(hook, message)
            except Exception as e:
                self.logger.error(f"Error in {hook_type} hook: {e}")

    async def _call_handler(self, handler: Callable, message: Message):
        """Helper method to call a handler with proper async support"""
        if callable(handler):
            result = handler(message)
            if hasattr(result, "__await__"):
                await result

    # Event handler registration
    def register_event_handler(self, event_type: str, handler: Callable[[Message], Any]):
        """
        Register a handler function for a specific event type.

        Args:
            event_type: The type of event to handle
            handler: Function that takes a Message object and handles the event
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        return self  # Allow for method chaining

    def register_global_event_handler(self, handler: Callable[[Message], Any]):
        """
        Register a handler function for all events.

        Args:
            handler: Function that takes a Message object and handles any event
        """
        self._global_event_handlers.append(handler)
        return self  # Allow for method chaining

    # Pre-event hook registration
    def register_pre_event_hook(self, event_type: str, hook: Callable[[Message], Any]):
        """
        Register a hook to execute before handlers for a specific event type.

        Args:
            event_type: The type of event to hook
            hook: Function that takes a Message object and runs before handlers
        """
        if event_type not in self._pre_event_hooks:
            self._pre_event_hooks[event_type] = []
        self._pre_event_hooks[event_type].append(hook)
        return self

    def register_global_pre_event_hook(self, hook: Callable[[Message], Any]):
        """
        Register a hook to execute before handlers for all events.

        Args:
            hook: Function that takes a Message object and runs before any handlers
        """
        self._global_pre_event_hooks.append(hook)
        return self

    # Post-event hook registration
    def register_post_event_hook(self, event_type: str, hook: Callable[[Message], Any]):
        """
        Register a hook to execute after handlers for a specific event type.

        Args:
            event_type: The type of event to hook
            hook: Function that takes a Message object and runs after handlers
        """
        if event_type not in self._post_event_hooks:
            self._post_event_hooks[event_type] = []
        self._post_event_hooks[event_type].append(hook)
        return self

    def register_global_post_event_hook(self, hook: Callable[[Message], Any]):
        """
        Register a hook to execute after handlers for all events.

        Args:
            hook: Function that takes a Message object and runs after all handlers
        """
        self._global_post_event_hooks.append(hook)
        return self

    # Unregister handlers
    def unregister_event_handler(self, event_type: str, handler: Optional[Callable] = None):
        """
        Unregister handler(s) for a specific event type.

        Args:
            event_type: The type of event
            handler: Optional handler to remove. If None, removes all handlers for this event type.
        """
        if event_type in self._event_handlers:
            if handler is None:
                self._event_handlers.pop(event_type)
            else:
                self._event_handlers[event_type] = [h for h in self._event_handlers[event_type] if h != handler]
        return self

    def unregister_global_event_handler(self, handler: Optional[Callable] = None):
        """
        Unregister global event handler(s).

        Args:
            handler: Optional handler to remove. If None, removes all global handlers.
        """
        if handler is None:
            self._global_event_handlers.clear()
        else:
            self._global_event_handlers = [h for h in self._global_event_handlers if h != handler]
        return self

    # Unregister pre-event hooks
    def unregister_pre_event_hook(self, event_type: str, hook: Optional[Callable] = None):
        """
        Unregister pre-event hook(s) for a specific event type.

        Args:
            event_type: The type of event
            hook: Optional hook to remove. If None, removes all pre-event hooks for this event type.
        """
        if event_type in self._pre_event_hooks:
            if hook is None:
                self._pre_event_hooks.pop(event_type)
            else:
                self._pre_event_hooks[event_type] = [h for h in self._pre_event_hooks[event_type] if h != hook]
        return self

    def unregister_global_pre_event_hook(self, hook: Optional[Callable] = None):
        """
        Unregister global pre-event hook(s).

        Args:
            hook: Optional hook to remove. If None, removes all global pre-event hooks.
        """
        if hook is None:
            self._global_pre_event_hooks.clear()
        else:
            self._global_pre_event_hooks = [h for h in self._global_pre_event_hooks if h != hook]
        return self

    # Unregister post-event hooks
    def unregister_post_event_hook(self, event_type: str, hook: Optional[Callable] = None):
        """
        Unregister post-event hook(s) for a specific event type.

        Args:
            event_type: The type of event
            hook: Optional hook to remove. If None, removes all post-event hooks for this event type.
        """
        if event_type in self._post_event_hooks:
            if hook is None:
                self._post_event_hooks.pop(event_type)
            else:
                self._post_event_hooks[event_type] = [h for h in self._post_event_hooks[event_type] if h != hook]
        return self

    def unregister_global_post_event_hook(self, hook: Optional[Callable] = None):
        """
        Unregister global post-event hook(s).

        Args:
            hook: Optional hook to remove. If None, removes all global post-event hooks.
        """
        if hook is None:
            self._global_post_event_hooks.clear()
        else:
            self._global_post_event_hooks = [h for h in self._global_post_event_hooks if h != hook]
        return self

    async def connect(self):
        try:
            self.ws = await websockets.connect(self.url, ping_interval=30, ping_timeout=10)
            self.logger.info("WebSocket connection opened.")
            initial_message = json.dumps(self.login_payload)
            self.logger.debug(f"Sending initial message: {initial_message}")
            await self.send_message(initial_message)
        except Exception:
            self.logger.exception("Connection error", exc_info=True)
            return False
        else:
            return True

    async def send_message(self, message):
        try:
            self.logger.debug(f"--> Sending: {message}")
            await self.ws.send(message)
        except Exception:
            self.logger.exception("Error sending message", exc_info=True)

    async def receive_messages(self):
        while True:
            try:
                message = await self.ws.recv()
                msg = self._extract_message_data(message)
                if msg:
                    await self.on_message(msg)
            except websockets.exceptions.ConnectionClosed:
                self.logger.info("WebSocket connection closed")
                break
            except Exception:
                self.logger.exception("Error in receive loop", exc_info=True)
                break

    async def start(self):
        self.running = True
        if await self.connect():
            self.logger.info("Connected to WebSocket server. Receiving messages...")
            await self.receive_messages()
        else:
            self.logger.exception("Failed to connect to WebSocket server", exc_info=True)

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
        if self.ws:
            await self.ws.close()
            self.logger.info("WebSocket client stopped.")
