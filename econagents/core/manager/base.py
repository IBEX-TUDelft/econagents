import asyncio
import json
import logging
import traceback
from typing import Any, Callable, Optional


from econagents.core.events import Message
from econagents.core.transport import WebSocketTransport, AuthenticationMechanism, SimpleLoginPayloadAuth
from econagents.core.logging_mixin import LoggerMixin


class AgentManager(LoggerMixin):
    """
    Agent Manager for handling WebSocket connections, message routing, and event handling.

    The AgentManager provides a high-level interface for connecting to a WebSocket server,
    sending messages, and routing received messages to appropriate handlers. It also
    supports pre- and post-event hooks for intercepting and processing messages.

    Connection parameters (URL and authentication mechanism) can be:
    1. Provided at initialization time
    2. Injected later using property setters:
       - manager.url = "wss://example.com/ws"
       - manager.auth_mechanism = SimpleLoginPayloadAuth()
       - manager.auth_mechanism_kwargs = {"username": "user", "password": "pass"}

    This delayed injection pattern allows for more flexible configuration and testing.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        auth_mechanism: Optional[AuthenticationMechanism] = None,
        auth_mechanism_kwargs: Optional[dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the AgentManager.

        Args:
            url: (Optional) WebSocket URL to connect to
            auth_mechanism: (Optional) Authentication mechanism
            auth_mechanism_kwargs: (Optional) Keyword arguments to pass to auth_mechanism
            logger: (Optional) Logger instance
        """
        if logger:
            self.logger = logger

        self._url = url
        self._auth_mechanism = auth_mechanism
        self._auth_mechanism_kwargs = auth_mechanism_kwargs
        self.transport = None
        self.running = False

        # Dictionary to store event handlers: {event_type: handler_function}
        self._event_handlers: dict[str, list[Callable[[Message], Any]]] = {}
        # Handler for all events (will be called for every event)
        self._global_event_handlers: list[Callable[[Message], Any]] = []

        # Pre and post event hooks
        # For specific events: {event_type: [hook_functions]}
        self._pre_event_hooks: dict[str, list[Callable[[Message], Any]]] = {}
        self._post_event_hooks: dict[str, list[Callable[[Message], Any]]] = {}
        # For all events
        self._global_pre_event_hooks: list[Callable[[Message], Any]] = []
        self._global_post_event_hooks: list[Callable[[Message], Any]] = []

        # Initialize transport if URL is provided
        if url:
            self._initialize_transport()

    @property
    def url(self) -> Optional[str]:
        """Get the WebSocket URL."""
        return self._url

    @url.setter
    def url(self, value: str):
        """
        Set the WebSocket URL.

        Args:
            value: WebSocket URL to connect to
        """
        self._url = value
        if self.transport is None:
            self._initialize_transport()
        else:
            self.transport.url = value

    @property
    def auth_mechanism(self) -> Optional[AuthenticationMechanism]:
        """Get the authentication mechanism."""
        return self._auth_mechanism

    @auth_mechanism.setter
    def auth_mechanism(self, value: AuthenticationMechanism):
        """
        Set the authentication mechanism.

        Args:
            value: Authentication mechanism
        """
        self._auth_mechanism = value
        if self.transport is not None:
            self.transport.auth_mechanism = value

    @property
    def auth_mechanism_kwargs(self) -> Optional[dict[str, Any]]:
        """Get the authentication mechanism keyword arguments."""
        return self._auth_mechanism_kwargs

    @auth_mechanism_kwargs.setter
    def auth_mechanism_kwargs(self, value: Optional[dict[str, Any]]):
        """
        Set the authentication mechanism keyword arguments.

        Args:
            value: Keyword arguments to pass to auth_mechanism
        """
        self._auth_mechanism_kwargs = value
        if self.transport is not None:
            self.transport.auth_mechanism_kwargs = value

    def _initialize_transport(self):
        """Initialize the WebSocketTransport with current configuration."""
        if not self._url:
            raise ValueError("URL must be set before initializing transport")

        self.transport = WebSocketTransport(
            url=self._url,
            logger=self.logger,
            on_message_callback=self._raw_message_received,
            auth_mechanism=self._auth_mechanism,
            auth_mechanism_kwargs=self._auth_mechanism_kwargs,
        )

    def _raw_message_received(self, raw_message: str):
        """Process raw message from the transport layer"""
        msg = self._extract_message_data(raw_message)
        if msg:
            asyncio.create_task(self.on_message(msg))
        return None

    def _extract_message_data(self, message: str) -> Optional[Message]:
        try:
            msg = json.loads(message)
            message_type = msg.get("type", "")
            event_type = msg.get("eventType", "")
            data = msg.get("data", {})
        except json.JSONDecodeError:
            self.logger.error("Invalid JSON received.")
            return None
        return Message(message_type=message_type, event_type=event_type, data=data)

    async def on_message(self, message: Message):
        """
        Default implementation to handle incoming messages from the server.

        For event-type messages, routes them to on_event.
        Subclasses can override this method for custom handling.
        """
        self.logger.debug(f"<-- AgentManager received message: {message}")
        if message.message_type == "event":
            await self.on_event(message)

    async def send_message(self, message: str):
        """Send a message through the transport layer."""
        if self.transport is None:
            self.logger.error("Cannot send message: transport not initialized")
            return
        await self.transport.send(message)

    async def start(self):
        """Start the agent manager and connect to the server."""
        if self.transport is None:
            if self.url:
                self._initialize_transport()
            else:
                raise ValueError("URL must be set before starting the agent manager")

        self.running = True
        connected = await self.transport.connect()
        if connected:
            self.logger.info("Connected to WebSocket server. Receiving messages...")
            await self.transport.start_listening()
        else:
            self.logger.error("Failed to connect to WebSocket server")

    async def stop(self):
        """Stop the agent manager and close the connection."""
        self.running = False
        if self.transport:
            await self.transport.stop()

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

    async def _execute_hooks(self, hooks: list[Callable], message: Message, hook_type: str) -> None:
        """Execute a list of hooks/handlers with proper error handling."""
        for hook in hooks:
            try:
                await self._call_handler(hook, message)
            except Exception as e:
                self.logger.error(
                    f"Error in {hook_type} ({hook.__name__}) hook: {e}, message: {message.model_dump()}",
                    extra={
                        "traceback": traceback.format_exc(),
                    },
                )

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
