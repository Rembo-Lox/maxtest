import logging
import ssl
from typing import Any

import httpx

from .config import settings
from .db import set_error, set_message_id

logger = logging.getLogger(__name__)


def json_shape(value: Any, depth: int = 0) -> object:
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            "type": "object",
            "keys": sorted(str(key) for key in value),
            "values": {str(key): json_shape(nested, depth + 1) for key, nested in value.items()},
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "length": len(value),
            "item": json_shape(value[0], depth + 1) if value else None,
        }
    return type(value).__name__


def find_upload_token(value: Any, path: str = "$") -> tuple[str | None, str | None]:
    if isinstance(value, dict):
        token = value.get("token")
        if isinstance(token, str) and token:
            return token, f"{path}.token"
        for key, nested in value.items():
            token, token_path = find_upload_token(nested, f"{path}.{key}")
            if token:
                return token, token_path
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            token, token_path = find_upload_token(nested, f"{path}[{index}]")
            if token:
                return token, token_path
    return None, None


def extract_upload_token(value: Any) -> str | None:
    return find_upload_token(value)[0]


def callback_keyboard(request_id: str) -> dict[str, Any]:
    delimiter = settings.callback_delimiter
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [[
                {"type": "callback", "text": settings.accept_button_text, "payload": f"{settings.accept_action}{delimiter}{request_id}"},
                {"type": "callback", "text": settings.reject_button_text, "payload": f"{settings.reject_action}{delimiter}{request_id}"},
            ]]
        },
    }


async def send_request(recipient_id: str, text: str, request_id: str, image: Any = None) -> str:
    if not settings.max_send_enabled:
        logger.info("MAX delivery disabled; request_id=%s", request_id)
        return ""
    if not settings.max_bot_token:
        logger.warning("MAX is not configured; request_id=%s", request_id)
        set_error(request_id)
        raise RuntimeError("MAX bot token is not configured")

    attachments: list[dict[str, Any]] = [callback_keyboard(request_id)]
    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            verify=ssl.create_default_context(),
        ) as client:
            images = image if isinstance(image, list) else ([image] if image is not None else [])
            for image_item in images[:11]:
                upload_response = await client.post(
                    f"{settings.max_api_url}/uploads",
                    params={"type": "image"},
                    headers={"Authorization": settings.max_bot_token},
                )
                upload_response.raise_for_status()
                upload_data = upload_response.json()
                logger.info(
                    "MAX upload init response status=%s content_type=%s structure=%s",
                    upload_response.status_code,
                    upload_response.headers.get("content-type", ""),
                    json_shape(upload_data),
                )
                upload_url = upload_data.get("url") if isinstance(upload_data, dict) else None
                if not isinstance(upload_url, str) or not upload_url:
                    raise ValueError("MAX upload init response did not contain upload URL")
                upload_token, token_path = find_upload_token(upload_data)
                uploaded = await client.post(
                    upload_url,
                    files={"data": (image_item.filename, image_item.content, image_item.content_type)},
                )
                uploaded.raise_for_status()
                uploaded_data = uploaded.json()
                uploaded_token, uploaded_token_path = find_upload_token(uploaded_data)
                upload_token = upload_token or uploaded_token
                logger.info(
                    "MAX image upload response status=%s content_type=%s structure=%s token_path=%s",
                    uploaded.status_code,
                    uploaded.headers.get("content-type", ""),
                    json_shape(uploaded_data),
                    token_path or uploaded_token_path or "none",
                )
                if not upload_token:
                    raise ValueError("MAX upload response did not contain image token")
                attachments.insert(0, {"type": "image", "payload": {"token": upload_token}})
            target_parameter = "chat_id" if settings.max_target_type == "chat" else "user_id"
            response = await client.post(
                f"{settings.max_api_url}/messages",
                params={target_parameter: recipient_id},
                headers={"Authorization": settings.max_bot_token},
                json={"text": text, "attachments": attachments},
            )
            response.raise_for_status()
            message_id = str(response.json().get("message", {}).get("body", {}).get("mid", ""))
            if not message_id:
                raise ValueError("MAX response did not contain message id")
            set_message_id(request_id, message_id)
            return message_id
    except (httpx.HTTPError, ValueError, KeyError) as error:
        logger.exception("MAX message delivery failed; request_id=%s", request_id)
        set_error(request_id)
        raise RuntimeError("MAX message delivery failed") from error


async def list_subscriptions() -> dict[str, Any]:
    if not settings.max_bot_token:
        raise RuntimeError("MAX bot token is not configured")
    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        verify=ssl.create_default_context(),
    ) as client:
        response = await client.get(
            f"{settings.max_api_url}/subscriptions",
            headers={"Authorization": settings.max_bot_token},
        )
        response.raise_for_status()
        data = response.json()
    subscriptions = data.get("subscriptions", []) if isinstance(data, dict) else []
    return {
        "subscriptions": [
            {
                "url": item.get("url"),
                "update_types": item.get("update_types"),
                "time": item.get("time"),
                "version": item.get("version"),
            }
            for item in subscriptions
            if isinstance(item, dict)
        ]
    }


async def answer_callback(callback_id: str, text: str = "") -> None:
    if not callback_id or not settings.max_bot_token:
        return
    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            verify=ssl.create_default_context(),
        ) as client:
            response = await client.post(
                f"{settings.max_api_url}/answers",
                params={"callback_id": callback_id},
                headers={"Authorization": settings.max_bot_token},
                json={"message": {"text": text, "notify": True}},
            )
            response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("MAX callback answer failed")
