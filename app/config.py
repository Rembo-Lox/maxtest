import os
import json
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def load_recipient_routes() -> dict[str, str]:
    raw_routes = os.getenv("MAX_RECIPIENT_ROUTES", "{}")
    try:
        routes = json.loads(raw_routes)
    except json.JSONDecodeError as error:
        raise RuntimeError("MAX_RECIPIENT_ROUTES must be valid JSON") from error
    if not isinstance(routes, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in routes.items()):
        raise RuntimeError("MAX_RECIPIENT_ROUTES must be a JSON object with string keys and values")
    return routes


@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv("DATABASE_PATH", "./data/app.db")
    bitrix_incoming_token: str = os.getenv("BITRIX_INCOMING_TOKEN", "")
    bitrix_webhook_url: str = os.getenv("BITRIX_WEBHOOK_URL", "")
    bitrix_text_field_title: str = os.getenv("BITRIX_TEXT_FIELD_TITLE", "Текст для MAX")
    bitrix_image_field_title: str = os.getenv("BITRIX_IMAGE_FIELD_TITLE", "Изображение для MAX")
    bitrix_recipient_field_title: str = os.getenv("BITRIX_RECIPIENT_FIELD_TITLE", "Получатель MAX")
    bitrix_status_field_title: str = os.getenv("BITRIX_STATUS_FIELD_TITLE", "Статус отправки в MAX")
    bitrix_responder_field_title: str = os.getenv("BITRIX_RESPONDER_FIELD_TITLE", "Ответил в MAX")
    allow_resend: bool = os.getenv("ALLOW_RESEND", "false").lower() in {"1", "true", "yes", "on"}
    sent_status_value: str = os.getenv("BITRIX_SENT_STATUS_VALUE", "Отправлено")
    accepted_status_value: str = os.getenv("BITRIX_ACCEPTED_STATUS_VALUE", "Принято")
    rejected_status_value: str = os.getenv("BITRIX_REJECTED_STATUS_VALUE", "Отказано")
    max_bot_token: str = os.getenv("MAX_BOT_TOKEN", "")
    max_webhook_secret: str = os.getenv("MAX_WEBHOOK_SECRET", "")
    max_webhook_url: str = os.getenv("MAX_WEBHOOK_URL", "https://rembovrc.ru/api/max/webhook")
    max_api_url: str = os.getenv("MAX_API_URL", "https://platform-api2.max.ru")
    max_send_enabled: bool = os.getenv("MAX_SEND_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    max_target_type: str = os.getenv("MAX_TARGET_TYPE", "user")
    max_chat_id: str = os.getenv("MAX_CHAT_ID", "")
    max_recipient_routes: dict[str, str] = field(default_factory=dict)
    request_id_prefix: str = os.getenv("REQUEST_ID_PREFIX", "req_")
    callback_delimiter: str = os.getenv("CALLBACK_DELIMITER", ":")
    accept_action: str = os.getenv("ACCEPT_ACTION", "accept")
    reject_action: str = os.getenv("REJECT_ACTION", "reject")
    responder_includes_result: bool = os.getenv("RESPONDER_INCLUDES_RESULT", "false").lower() in {"1", "true", "yes", "on"}
    accept_button_text: str = os.getenv("ACCEPT_BUTTON_TEXT", "Принять")
    reject_button_text: str = os.getenv("REJECT_BUTTON_TEXT", "Отказать")
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_recipient_routes", load_recipient_routes())


settings = Settings()
