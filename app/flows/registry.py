from collections.abc import (
    Awaitable,
    Callable,
)

Handler = Callable[..., Awaitable[None]]

_postback_handlers: dict[str, Handler] = {}
_message_handlers: dict[str, Handler] = {}


def _registrar(registry: dict[str, Handler], *keys: str):
    def decorator(handler: Handler) -> Handler:
        for key in keys:
            if key in registry:
                raise ValueError(f"Handler already registered: {key}")
            registry[key] = handler
        return handler

    return decorator


def register_postback(action: str):
    return _registrar(_postback_handlers, action)


def register_message(*message_types: str):
    return _registrar(_message_handlers, *message_types)


get_postback_handler = _postback_handlers.get
get_message_handler = _message_handlers.get
