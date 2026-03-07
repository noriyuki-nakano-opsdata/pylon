"""A2A wire DTOs and boundary validation.

Owns JSON-RPC params/result contract at the A2A protocol boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pylon.protocols.a2a.types import PushNotificationConfig


class DtoValidationError(ValueError):
    """Raised when A2A wire payload fails DTO validation."""


def _as_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DtoValidationError(f"'{field_name}' must be an object")
    return value


def _as_optional_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _as_object(value, field_name=field_name)


def _get_required_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise DtoValidationError(f"'{key}' must be a non-empty string")
    return value


def _get_optional_str(obj: dict[str, Any], key: str, default: str = "") -> str:
    value = obj.get(key, default)
    if not isinstance(value, str):
        raise DtoValidationError(f"'{key}' must be a string")
    return value


@dataclass(frozen=True)
class SendTaskParamsDTO:
    sender: str
    task: dict[str, Any]

    @classmethod
    def from_params(cls, params: Any) -> SendTaskParamsDTO:
        obj = _as_optional_object(params, field_name="params")
        task = _as_object(obj.get("task"), field_name="task")
        return cls(
            sender=_get_optional_str(obj, "sender", ""),
            task=task,
        )


@dataclass(frozen=True)
class TaskIdParamsDTO:
    task_id: str

    @classmethod
    def from_params(cls, params: Any) -> TaskIdParamsDTO:
        obj = _as_optional_object(params, field_name="params")
        return cls(task_id=_get_required_str(obj, "taskId"))

    @classmethod
    def from_client_input(cls, task_id: str) -> TaskIdParamsDTO:
        if not isinstance(task_id, str) or not task_id:
            raise DtoValidationError("'taskId' must be a non-empty string")
        return cls(task_id=task_id)

    def to_wire(self) -> dict[str, Any]:
        return {"taskId": self.task_id}


@dataclass(frozen=True)
class PushNotificationSetParamsDTO:
    task_id: str
    push_notification: PushNotificationConfig

    @classmethod
    def from_params(cls, params: Any) -> PushNotificationSetParamsDTO:
        obj = _as_optional_object(params, field_name="params")
        config_data = _as_object(
            obj.get("pushNotification"),
            field_name="pushNotification",
        )
        return cls(
            task_id=_get_required_str(obj, "taskId"),
            push_notification=PushNotificationConfig.from_dict(config_data),
        )


def push_notification_payload(
    *,
    task_id: str,
    push_notification: PushNotificationConfig | None,
) -> dict[str, Any]:
    return {
        "taskId": task_id,
        "pushNotification": push_notification.to_dict() if push_notification else None,
    }

