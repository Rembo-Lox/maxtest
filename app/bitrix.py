import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadedFile:
    file_id: str
    content: bytes
    filename: str
    content_type: str


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    title: str
    type: str
    metadata: dict[str, Any]
    enum_id_to_value: dict[str, str]


@dataclass(frozen=True)
class FieldMap:
    text: FieldDefinition
    image: FieldDefinition
    recipient: FieldDefinition
    status: FieldDefinition
    responder: FieldDefinition


_field_map_cache: FieldMap | None = None


class BitrixClient:
    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not settings.bitrix_webhook_url:
            raise RuntimeError("BITRIX_WEBHOOK_URL is not configured")
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(
                f"{settings.bitrix_webhook_url.rstrip('/')}/{method}",
                json=params,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("error"):
                raise RuntimeError(f"Bitrix REST error: {data['error']}")
            return data.get("result", {})

    async def get_deal(self, deal_id: str) -> dict[str, Any]:
        result = await self.call(
            "crm.item.get", {"entityTypeId": 2, "id": int(deal_id), "useOriginalUfNames": "Y"}
        )
        return result.get("item", result)

    async def get_fields(self) -> dict[str, Any]:
        result = await self.call("crm.item.fields", {"entityTypeId": 2, "useOriginalUfNames": "Y"})
        return result.get("fields", result)

    async def get_field_map(self, force_refresh: bool = False) -> FieldMap:
        global _field_map_cache
        if _field_map_cache is not None and not force_refresh:
            return _field_map_cache
        fields = await self.get_fields()

        def resolve(title: str, required: bool = True) -> FieldDefinition | None:
            matches = [(name, info) for name, info in fields.items() if isinstance(info, dict) and info.get("title") == title]
            if len(matches) > 1:
                raise RuntimeError(f"Multiple Bitrix fields found with title: {title}")
            if not matches:
                if required:
                    raise RuntimeError(f"Bitrix field not found by title: {title}")
                return None
            name, info = matches[0]
            return FieldDefinition(name, title, str(info.get("type", "")), info, self.enum_map(info))

        _field_map_cache = FieldMap(
            text=resolve(settings.bitrix_text_field_title),
            image=resolve(settings.bitrix_image_field_title),
            recipient=resolve(settings.bitrix_recipient_field_title),
            status=resolve(settings.bitrix_status_field_title),
            responder=resolve(settings.bitrix_responder_field_title),
        )
        return _field_map_cache

    async def refresh_field_map(self) -> FieldMap:
        return await self.get_field_map(force_refresh=True)

    @staticmethod
    def enum_map(field_info: dict[str, Any]) -> dict[str, str]:
        values: dict[str, str] = {}

        def visit(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                if "ID" in value and "VALUE" in value:
                    values[str(value["ID"])] = str(value["VALUE"])
                elif "id" in value and ("value" in value or "VALUE" in value):
                    values[str(value["id"])] = str(value.get("value", value.get("VALUE")))
                for item in value.values():
                    visit(item)

        visit(field_info)
        return values

    async def download_file(self, file_info: dict[str, Any]) -> DownloadedFile:
        url = str(file_info.get("urlMachine", ""))
        if not url:
            raise RuntimeError("Bitrix file has no urlMachine")
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        filename = str(file_info.get("name") or f"bitrix-{file_info.get('id', 'file')}")
        return DownloadedFile(str(file_info.get("id", "")), response.content, filename, content_type)

    async def update_deal(self, deal_id: str, fields: dict[str, Any]) -> None:
        if not settings.bitrix_webhook_url:
            logger.warning("Bitrix is not configured; deal_id=%s", deal_id)
            return
        if not fields:
            return
        await self.call("crm.item.update", {"entityTypeId": 2, "id": int(deal_id), "fields": fields, "useOriginalUfNames": "Y"})

    async def add_timeline_comment(self, deal_id: str, text: str) -> None:
        if not settings.bitrix_webhook_url:
            return
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(
                f"{settings.bitrix_webhook_url.rstrip('/')}/crm.timeline.comment.add",
                json={"fields": {"ENTITY_ID": deal_id, "ENTITY_TYPE": "deal", "COMMENT": text}},
            )
            response.raise_for_status()
