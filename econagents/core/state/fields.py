from typing import Any, Callable, Optional

from pydantic import Field


def EventField(
    default: Any = ...,
    *,
    default_factory: Optional[Callable[[], Any]] = None,
    event_key: Optional[str] = None,
    exclude_from_mapping: bool = False,
    events: Optional[list[str]] = None,
    exclude_events: Optional[list[str]] = None,
    **kwargs: Any,
) -> Any:
    """
    Create a field with event mapping metadata.

    Args:
        default (Any): Default value for the field
        default_factory (Callable[[], Any]): Factory function to generate default value
        event_key (Optional[str]): The key in event data that maps to this field
        exclude_from_mapping (bool): Whether to exclude this field from event mapping
        events (Optional[list[str]]): Optional list of events where this mapping should be applied
        exclude_events (Optional[list[str]]): Optional list of events where this mapping should not be applied
        **kwargs: Additional arguments to pass to Pydantic's Field

    Returns:
        FieldInfo: A Pydantic FieldInfo object with event mapping metadata
    """
    # Create a dictionary for custom metadata
    event_metadata = {
        "event_key": event_key,
        "exclude_from_mapping": exclude_from_mapping,
        "events": events,
        "exclude_events": exclude_events,
    }

    # Store metadata in json_schema_extra
    if "json_schema_extra" in kwargs:
        kwargs["json_schema_extra"].update({"event_metadata": event_metadata})
    else:
        kwargs["json_schema_extra"] = {"event_metadata": event_metadata}

    # Create the field with Pydantic's Field
    if default is not ...:
        return Field(default=default, **kwargs)
    elif default_factory is not None:
        return Field(default_factory=default_factory, **kwargs)
    else:
        return Field(**kwargs)
