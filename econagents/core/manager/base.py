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
    Agent Manager for handling connections, message routing, and event handling.

    The AgentManager provides a high-level interface for connecting to a server,
    sending messages, and routing received messages to appropriate handlers. It also
    supports pre- and post-event hooks for intercepting and processing messages.

    Connection parameters (URL and authentication mechanism) can be:

    1. Provided at initialization time

    2. Injected later using property setters:

        - manager.url = "wss://example.com/ws"

        - manager.auth_mechanism = SimpleLoginPayloadAuth()

        - manager.auth_mechanism_kwargs = {"username": "user", "password": "pass"}

    This delayed injection pattern allows for more flexible configuration and testing.

    Args:
        url (Optional[str]): WebSocket URL to connect to
        auth_mechanism (Optional[AuthenticationMechanism]): Authentication mechanism
        auth_mechanism_kwargs (Optional[dict[str, Any]]): Keyword arguments to pass to auth_mechanism
        logger (Optional[logging.Logger]): Logger instance
    """

    def __init__(
        self,
        url: Optional[str] = None,
        auth_mechanism: Optional[AuthenticationMechanism] = None,
        auth_mechanism_kwargs: Optional[dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
    ):
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

        # Default event type to trigger stopping the agent
        self._end_game_event_type: str = "game-over"
        self.register_event_handler(self._end_game_event_type, self._handle_end_game)

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
            value (str): WebSocket URL to connect to
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
            value (AuthenticationMechanism): Authentication mechanism
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
            value (Optional[dict[str, Any]]): Keyword arguments to pass to auth_mechanism
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

    async def _raw_message_received(self, raw_message: str):
        """Process raw message from the transport layer"""
        msg = self._extract_message_data(raw_message)
        if msg:
            asyncio.create_task(self.on_message(msg))
        return None

    def _extract_message_data(self, raw_message: str) -> Optional[Message]:
        try:
            msg = json.loads(raw_message)
            message_type = msg.get("type", "")
            event_type = msg.get("eventType", "")
            data = msg.get("data", {})
        except json.JSONDecodeError:
            self.logger.error("Invalid JSON received.")
            return None
        return Message(message_type=message_type, event_type=event_type, data=data)

    @property
    def end_game_event_type(self) -> str:
        """Get the event type that triggers the agent to stop."""
        return self._end_game_event_type

    @end_game_event_type.setter
    def end_game_event_type(self, value: str):
        """
        Set the event type that triggers the agent to stop.

        Unregisters the stop handler from the old event type and registers it
        for the new event type.

        Args:
            value (str): The new event type to listen for.
        """
        if self._end_game_event_type != value:
            # Unregister from the old event type
            self.unregister_event_handler(self._end_game_event_type, self._handle_end_game)
            # Register for the new event type
            self._end_game_event_type = value
            self.register_event_handler(self._end_game_event_type, self._handle_end_game)
            self.logger.info(f"End game event type set to: {value}")

    async def on_message(self, message: Message):
        """
        Default implementation to handle incoming messages from the server.

        For event-type messages, routes them to on_event.
        Subclasses can override this method for custom handling.

        Args:
            message (Message): Incoming message from the server
        """
        self.logger.debug(f"<-- AgentManager received message: {message}")
        if message.message_type == "event":
            await self.on_event(message)

    async def send_message(self, message: str):
        """Send a message through the transport layer.

        Args:
            message (str): Message to send
        """
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
        self.logger.info("Starting agent manager. Receiving messages...")
        await self.transport.start_listening()

    async def stop(self):
        """Stop the agent manager and close the connection."""
        self.running = False
        if self.transport:
            await self.transport.stop()
        self.logger.info("Agent manager stopped and connection closed.")

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

        Args:
            message (Message): Incoming event message from the server
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

    async def _handle_end_game(self, message: Message):
        """
        Default handler for the 'end_game_event_type'. Stops the agent manager.

        Args:
            message (Message): The event message triggering the end game.
        """
        self.logger.info(f"Received end game event ({message.event_type}). Stopping agent manager...")
        await self.stop()

    # Event handler registration
    def register_event_handler(self, event_type: str, handler: Callable[[Message], Any]):
        """
        Register a handler function for a specific event type.

        Args:
            event_type (str): The type of event to handle
            handler (Callable[[Message], Any]): Function that takes a Message object and handles the event
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        return self  # Allow for method chaining

    def register_global_event_handler(self, handler: Callable[[Message], Any]):
        """
        Register a handler function for all events.

        Args:
            handler (Callable[[Message], Any]): Function that takes a Message object and handles any event
        """
        self._global_event_handlers.append(handler)
        return self  # Allow for method chaining

    # Pre-event hook registration
    def register_pre_event_hook(self, event_type: str, hook: Callable[[Message], Any]):
        """
        Register a hook to execute before handlers for a specific event type.

        Args:
            event_type (str): The type of event to hook
            hook (Callable[[Message], Any]): Function that takes a Message object and runs before handlers
        """
        if event_type not in self._pre_event_hooks:
            self._pre_event_hooks[event_type] = []
        self._pre_event_hooks[event_type].append(hook)
        return self

    def register_global_pre_event_hook(self, hook: Callable[[Message], Any]):
        """
        Register a hook to execute before handlers for all events.

        Args:
            hook (Callable[[Message], Any]): Function that takes a Message object and runs before any handlers
        """
        self._global_pre_event_hooks.append(hook)
        return self

    # Post-event hook registration
    def register_post_event_hook(self, event_type: str, hook: Callable[[Message], Any]):
        """
        Register a hook to execute after handlers for a specific event type.

        Args:
            event_type (str): The type of event to hook
            hook (Callable[[Message], Any]): Function that takes a Message object and runs after handlers
        """
        if event_type not in self._post_event_hooks:
            self._post_event_hooks[event_type] = []
        self._post_event_hooks[event_type].append(hook)
        return self

    def register_global_post_event_hook(self, hook: Callable[[Message], Any]):
        """
        Register a hook to execute after handlers for all events.

        Args:
            hook (Callable[[Message], Any]): Function that takes a Message object and runs after all handlers
        """
        self._global_post_event_hooks.append(hook)
        return self

    # Unregister handlers
    def unregister_event_handler(self, event_type: str, handler: Optional[Callable] = None):
        """
        Unregister handler(s) for a specific event type.

        Args:
            event_type (str): The type of event
            handler (Optional[Callable]): Optional handler to remove. If None, removes all handlers for this event type.
        """
        if event_type in self._event_handlers:
            if handler is None:
                self._event_handlers.pop(event_type)
            else:
                # Use list comprehension to avoid modifying list while iterating
                handlers_to_keep = [h for h in self._event_handlers[event_type] if h != handler]
                if not handlers_to_keep:
                    # Remove the key if the list becomes empty
                    self._event_handlers.pop(event_type, None)
                else:
                    self._event_handlers[event_type] = handlers_to_keep
                # Explicitly handle removal of the default end game handler
                if event_type == self._end_game_event_type and handler == self._handle_end_game:
                    self.logger.warning(f"Default end game handler for '{event_type}' unregistered.")

        return self

    def unregister_global_event_handler(self, handler: Optional[Callable] = None):
        """
        Unregister global event handler(s).

        Args:
            handler (Optional[Callable]): Optional handler to remove. If None, removes all global handlers.
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
            event_type (str): The type of event
            hook (Optional[Callable]): Optional hook to remove. If None, removes all pre-event hooks for this event type.
        """
        if event_type in self._pre_event_hooks:
            if hook is None:
                self._pre_event_hooks.pop(event_type)
            else:
                # Use list comprehension to avoid modifying list while iterating
                hooks_to_keep = [h for h in self._pre_event_hooks[event_type] if h != hook]
                if not hooks_to_keep:
                    # Remove the key if the list becomes empty
                    self._pre_event_hooks.pop(event_type, None)
                else:
                    self._pre_event_hooks[event_type] = hooks_to_keep
        return self

    def unregister_global_pre_event_hook(self, hook: Optional[Callable] = None):
        """
        Unregister global pre-event hook(s).

        Args:
            hook (Optional[Callable]): Optional hook to remove. If None, removes all global pre-event hooks.
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
            event_type (str): The type of event
            hook (Optional[Callable]): Optional hook to remove. If None, removes all post-event hooks for this event type.
        """
        if event_type in self._post_event_hooks:
            if hook is None:
                self._post_event_hooks.pop(event_type)
            else:
                # Use list comprehension to avoid modifying list while iterating
                hooks_to_keep = [h for h in self._post_event_hooks[event_type] if h != hook]
                if not hooks_to_keep:
                    # Remove the key if the list becomes empty
                    self._post_event_hooks.pop(event_type, None)
                else:
                    self._post_event_hooks[event_type] = hooks_to_keep
        return self

    def unregister_global_post_event_hook(self, hook: Optional[Callable] = None):
        """
        Unregister global post-event hook(s).

        Args:
            hook (Optional[Callable]): Optional hook to remove. If None, removes all global post-event hooks.
        """
        if hook is None:
            self._global_post_event_hooks.clear()
        else:
            self._global_post_event_hooks = [h for h in self._global_post_event_hooks if h != hook]
        return self
