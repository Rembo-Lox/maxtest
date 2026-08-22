import logging
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from . import db
from .bitrix import BitrixClient, DownloadedFile, FieldMap
from .config import settings
from .max_api import answer_callback, list_subscriptions, send_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
for noisy_logger in ("httpx", "httpcore"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class BitrixMessage(BaseModel):
    deal_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=20)
    text: str = Field(min_length=1, max_length=4000)
    recipient: str | None = Field(default=None, max_length=100)
    chat_id: str | None = Field(default=None, max_length=100)
    image_id: str | None = Field(default=None, max_length=100)


@dataclass(frozen=True)
class DealData:
    id: str
    text: str
    recipient: str
    image_files: list[dict]
    status: str


def verify_token(provided: str | None, expected: str) -> None:
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def resolve_recipient(message: BitrixMessage) -> str:
    if message.chat_id:
        return message.chat_id
    if message.recipient and settings.max_recipient_routes:
        chat_id = settings.max_recipient_routes.get(message.recipient)
        if chat_id:
            return chat_id
        raise HTTPException(status_code=422, detail="Unknown recipient")
    recipient_id = message.recipient or settings.max_chat_id
    if not recipient_id:
        raise HTTPException(status_code=422, detail="recipient or chat_id is required")
    return recipient_id


def iter_updates(payload: dict) -> list[dict]:
    updates = payload.get("updates")
    if not isinstance(updates, list):
        return [payload]
    envelope = {key: value for key, value in payload.items() if key != "updates"}
    return [{**envelope, **item} for item in updates if isinstance(item, dict)]


def extract_callback(payload: dict) -> tuple[str, str, str, str, str] | None:
    update_type = payload.get("update_type")
    if update_type is not None and update_type != "message_callback":
        return None
    callback = payload.get("callback")
    if not isinstance(callback, dict):
        callback = payload
    callback_payload = callback.get("payload")
    payload_data = callback_payload if isinstance(callback_payload, dict) else {}
    action = str(callback.get("action", payload_data.get("action", ""))).strip()
    request_id = str(callback.get("request_id", payload_data.get("request_id", ""))).strip()
    if not action or not request_id:
        raw = str(callback_payload or "")
        action, separator, request_id = raw.partition(settings.callback_delimiter)
        if not separator:
            return None
        action = action.strip()
        request_id = request_id.strip()
    if action not in {settings.accept_action, settings.reject_action} or not request_id:
        return None
    callback_id = str(callback.get("callback_id") or payload.get("callback_id", "")).strip()
    user = callback.get("user") or payload.get("user") or payload_data.get("user") or {}
    if not isinstance(user, dict):
        return None
    user_id = str(user.get("user_id") or user.get("id") or callback.get("responder_id", "")).strip()
    user_name = str(user.get("name") or user.get("display_name") or callback.get("responder_name") or callback.get("responder") or "").strip()
    if not user_id and not user_name:
        return None
    return action, request_id, user_id, user_name or user_id, callback_id


def callback_shape(payload: dict) -> dict[str, object]:
    callback = payload.get("callback")
    return {
        "update_type": str(payload.get("update_type", "")),
        "top_level_keys": sorted(str(key) for key in payload),
        "callback_keys": sorted(str(key) for key in callback) if isinstance(callback, dict) else [],
        "payload_type": type(callback.get("payload")).__name__ if isinstance(callback, dict) else "none",
        "has_updates": isinstance(payload.get("updates"), list),
        "has_callback_id": bool(
            (callback.get("callback_id") if isinstance(callback, dict) else None)
            or payload.get("callback_id")
        ),
    }


def file_list(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return [value] if isinstance(value, dict) else []


def field_value(item: dict, field_name: str) -> object:
    return item.get(field_name)


def as_text(value: object) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        return str(value.get("value", value.get("VALUE", value.get("id", value.get("ID", "")))))
    return str(value or "").strip()


async def prepare_deal(deal_id: str) -> tuple[DealData, str, list[DownloadedFile], BitrixClient, FieldMap]:
    client = BitrixClient()
    for attempt in range(2):
        try:
            field_map = await client.get_field_map(force_refresh=attempt == 1)
            deal = await client.get_deal(deal_id)
            required_fields = (field_map.text.name, field_map.image.name, field_map.recipient.name, field_map.status.name)
            if any(field_name not in deal for field_name in required_fields):
                raise KeyError("Bitrix deal response does not contain resolved fields")
            text = as_text(field_value(deal, field_map.text.name))
            raw_recipient = as_text(field_value(deal, field_map.recipient.name))
            recipient = field_map.recipient.enum_id_to_value.get(raw_recipient, raw_recipient)
            current_status = field_map.status.enum_id_to_value.get(as_text(field_value(deal, field_map.status.name)), as_text(field_value(deal, field_map.status.name)))
            if not settings.allow_resend and current_status in {settings.sent_status_value, settings.accepted_status_value, settings.rejected_status_value}:
                raise HTTPException(status_code=409, detail="Deal message has already been sent")
            if not text or not recipient:
                raise HTTPException(status_code=422, detail="Deal text or recipient is empty")
            target_chat_id = settings.max_recipient_routes.get(recipient)
            if not target_chat_id:
                logger.error("Unknown Bitrix recipient value=%s deal_id=%s", recipient, deal_id)
                raise HTTPException(status_code=422, detail="Unknown recipient value")
            files = file_list(field_value(deal, field_map.image.name))
            images = [await client.download_file(file_info) for file_info in files[:11]]
            return DealData(deal_id, text, recipient, files, current_status), target_chat_id, images, client, field_map
        except KeyError:
            if attempt == 1:
                raise
    raise RuntimeError("Unable to prepare deal")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if settings.bitrix_webhook_url:
        try:
            await BitrixClient().get_field_map()
        except Exception as error:
            logger.error("Bitrix metadata preload failed error_type=%s", type(error).__name__)
    yield


app = FastAPI(title="Bitrix24 to MAX integration", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/api/bitrix/send", methods=["GET", "POST"], status_code=200)
async def bitrix_send(
    request: Request,
    x_bitrix_token: str | None = Header(default=None),
) -> dict[str, str]:
    verify_token(x_bitrix_token or request.query_params.get("token"), settings.bitrix_incoming_token)
    try:
        deal_id = request.query_params.get("deal_id")
        if not deal_id and request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
            deal_id = body.get("deal_id") if isinstance(body, dict) else None
        if not deal_id:
            raise HTTPException(status_code=422, detail="deal_id is required")
        deal_id = BitrixMessage(deal_id=deal_id, text="x").deal_id
    except ValueError as error:
        raise HTTPException(status_code=422, detail="deal_id must be a positive integer") from error
    try:
        deal, target_chat_id, image, client, field_map = await prepare_deal(deal_id)
        request_id = f"{settings.request_id_prefix}{secrets.token_urlsafe(16)}"
        db.create_request(
            request_id,
            deal_id,
            target_chat_id,
            deal.image_files[0].get("id") if deal.image_files else None,
            deal.recipient,
            target_chat_id,
            deal.text,
        )
        if settings.max_send_enabled:
            await send_request(target_chat_id, deal.text, request_id, image)
            sent_id = next((item_id for item_id, value in field_map.status.enum_id_to_value.items() if value == settings.sent_status_value), None)
            if not sent_id:
                raise RuntimeError("Bitrix status value for sent message was not found")
            await client.update_deal(deal_id, {field_map.status.name: sent_id})
            db.set_status(request_id, "pending")
        logger.info("Bitrix deal prepared request_id=%s deal_id=%s recipient=%s image_count=%s", request_id, deal_id, deal.recipient, len(deal.image_files))
        return {"request_id": request_id, "status": "accepted", "deal_id": deal_id, "recipient": deal.recipient}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Bitrix request failed deal_id=%s error_type=%s", deal_id, type(error).__name__)
        detail = str(error) if isinstance(error, RuntimeError) else "Bitrix integration failed"
        raise HTTPException(status_code=502, detail=detail) from error


@app.get("/api/max/subscriptions")
async def max_subscriptions(
    request: Request,
    x_bitrix_token: str | None = Header(default=None),
) -> dict[str, object]:
    verify_token(x_bitrix_token or request.query_params.get("token"), settings.bitrix_incoming_token)
    return await list_subscriptions()


@app.post("/api/max/webhook", status_code=200)
async def max_webhook(
    request: Request,
    x_max_bot_api_secret: str | None = Header(default=None),
) -> dict[str, str]:
    provided_secret = x_max_bot_api_secret or request.query_params.get("secret")
    if not provided_secret:
        logger.warning("MAX webhook rejected: X-Max-Bot-Api-Secret header is missing; recreate the subscription with the secret")
    verify_token(provided_secret, settings.max_webhook_secret)
    try:
        event = await request.json()
    except ValueError:
        logger.warning("MAX webhook ignored: body is not valid JSON")
        return {"status": "ignored"}
    if not isinstance(event, dict):
        logger.warning("MAX webhook ignored: payload is not an object")
        return {"status": "ignored"}
    statuses = []
    for update in iter_updates(event):
        logger.info("MAX update received shape=%s", callback_shape(update))
        statuses.append(await process_update(update))
    return {"status": statuses[0] if len(statuses) == 1 else ("processed" if "processed" in statuses else "ignored")}


async def process_update(event: dict) -> str:
    callback = extract_callback(event)
    if callback is None:
        logger.warning("MAX callback ignored: unsupported shape")
        return "ignored"
    action, request_id, user_id, user_name, callback_id = callback
    logger.info(
        "MAX callback parsed action=%s request_id=%s has_callback_id=%s responder_id_present=%s responder_name_present=%s",
        action,
        request_id,
        bool(callback_id),
        bool(user_id),
        bool(user_name),
    )
    claim_status, record = db.claim_callback(request_id, action, user_id, user_name)
    if record is None:
        logger.warning("MAX callback not claimed request_id=%s claim_status=%s", request_id, claim_status)
        await answer_callback(callback_id, "Заявка не найдена" if claim_status == "unknown_request" else "Уже обработано")
        return claim_status
    await answer_callback(callback_id, "Обработано")
    result = settings.accepted_status_value if action == settings.accept_action else settings.rejected_status_value
    try:
        client = BitrixClient()
        field_map = await client.get_field_map()
        status_id = next((item_id for item_id, value in field_map.status.enum_id_to_value.items() if value == result), None)
        if status_id is None:
            raise RuntimeError(f"Bitrix status value not found: {result}")
        responder_value = f"{user_name} — {result}" if settings.responder_includes_result else user_name
        fields = {field_map.status.name: status_id, field_map.responder.name: responder_value}
        if not record["bitrix_updated_at"]:
            await client.update_deal(record["deal_id"], fields)
            db.mark_bitrix_updated(request_id)
        comment = f"MAX: сообщение {'принято' if action == settings.accept_action else 'отказано'}. Ответил: {user_name}."
        if not record["comment_added_at"]:
            await client.add_timeline_comment(record["deal_id"], comment)
            db.mark_comment_added(request_id)
        db.complete_callback(request_id, "accepted" if action == settings.accept_action else "rejected")
    except Exception:
        db.release_callback(request_id)
        logger.exception("Bitrix update failed; request_id=%s", request_id)
        return "retryable_error"
    logger.info("Bitrix deal updated deal_id=%s status=%s responder=%s", record["deal_id"], result, user_name)
    return "processed"
