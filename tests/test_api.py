import os
import tempfile
from types import SimpleNamespace

os.environ["BITRIX_INCOMING_TOKEN"] = "bitrix-secret"
os.environ["MAX_WEBHOOK_SECRET"] = "max-secret"
os.environ["MAX_BOT_TOKEN"] = ""
os.environ["MAX_SEND_ENABLED"] = "false"
os.environ["BITRIX_WEBHOOK_URL"] = ""
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), "maxtest-api.db")

if os.path.exists(os.environ["DATABASE_PATH"]):
    os.unlink(os.environ["DATABASE_PATH"])

from fastapi.testclient import TestClient

from app import db
from app import main
from app.main import app


def test_bitrix_send_requires_token():
    with TestClient(app) as client:
        response = client.post("/api/bitrix/send", json={"deal_id": "1", "text": "x", "recipient": "2"})
    assert response.status_code == 401


def test_callback_is_idempotent(monkeypatch):
    calls = []

    class SuccessfulBitrix:
        async def get_field_map(self):
            return SimpleNamespace(
                status=SimpleNamespace(name="UF_STATUS", enum_id_to_value={"68": "Принято"}),
                responder=SimpleNamespace(name="UF_RESPONDER"),
            )

        async def update_deal(self, deal_id, fields):
            calls.append((deal_id, fields))

        async def add_timeline_comment(self, deal_id, text):
            calls.append((deal_id, text))

    monkeypatch.setattr(main, "BitrixClient", SuccessfulBitrix)
    with TestClient(app) as client:
        request_id = "request-for-idempotency"
        db.create_request(request_id, "1", "2")
        event = {
            "update_type": "message_callback",
            "callback": {"payload": f"accept:{request_id}"},
            "user": {"user_id": 7, "name": "Ivan"},
        }
        first = client.post("/api/max/webhook", headers={"X-Max-Bot-Api-Secret": "max-secret"}, json=event)
        second = client.post("/api/max/webhook", headers={"X-Max-Bot-Api-Secret": "max-secret"}, json=event)
    assert first.json() == {"status": "processed"}
    assert second.json() == {"status": "already_processed"}
    assert calls == [
        ("1", {"UF_STATUS": "68", "UF_RESPONDER": "Ivan"}),
        ("1", "MAX: сообщение принято. Ответил: Ivan."),
    ]


def test_callback_bitrix_failure_is_retryable(monkeypatch):
    calls = []

    class FailingBitrix:
        async def get_field_map(self):
            return SimpleNamespace(
                status=SimpleNamespace(name="UF_STATUS", enum_id_to_value={"68": "Принято"}),
                responder=SimpleNamespace(name="UF_RESPONDER"),
            )

        async def update_deal(self, deal_id, fields):
            calls.append("update")
            raise RuntimeError("temporary Bitrix error")

        async def add_timeline_comment(self, deal_id, text):
            calls.append("comment")

    monkeypatch.setattr(main, "BitrixClient", FailingBitrix)
    with TestClient(app) as client:
        request_id = "request-for-retry"
        db.create_request(request_id, "2", "2")
        event = {"update_type": "message_callback", "callback": {"payload": f"accept:{request_id}"}, "user": {"user_id": 7, "name": "Ivan"}}
        first = client.post("/api/max/webhook", headers={"X-Max-Bot-Api-Secret": "max-secret"}, json=event)
    assert first.json() == {"status": "retryable_error"}
    assert calls == ["update"]


def test_structured_callback_uses_responder_id(monkeypatch):
    calls = []

    class SuccessfulBitrix:
        async def get_field_map(self):
            return SimpleNamespace(
                status=SimpleNamespace(name="UF_STATUS", enum_id_to_value={"69": "Отказано"}),
                responder=SimpleNamespace(name="UF_RESPONDER"),
            )

        async def update_deal(self, deal_id, fields):
            calls.append((deal_id, fields))

        async def add_timeline_comment(self, deal_id, text):
            calls.append((deal_id, text))

    monkeypatch.setattr(main, "BitrixClient", SuccessfulBitrix)
    with TestClient(app) as client:
        request_id = "structured-callback"
        db.create_request(request_id, "3", "2")
        event = {
            "update_type": "message_callback",
            "callback": {"action": "reject", "request_id": request_id, "responder_id": "42"},
        }
        response = client.post("/api/max/webhook", headers={"X-Max-Bot-Api-Secret": "max-secret"}, json=event)
    assert response.json() == {"status": "processed"}
    assert calls == [
        ("3", {"UF_STATUS": "69", "UF_RESPONDER": "42"}),
        ("3", "MAX: сообщение отказано. Ответил: 42."),
    ]


def test_extract_upload_token_supports_nested_response():
    from app.max_api import extract_upload_token, json_shape

    response = {"photos": {"photo-id": {"token": "image-token"}}}
    assert extract_upload_token(response) == "image-token"
    assert "image-token" not in str(json_shape(response))


def test_extract_upload_token_returns_none_for_unexpected_response():
    from app.max_api import extract_upload_token

    assert extract_upload_token({"photos": [], "status": "ok"}) is None


def test_nested_max_callback_updates_bitrix(monkeypatch):
    calls = []

    class SuccessfulBitrix:
        async def get_field_map(self):
            return SimpleNamespace(
                status=SimpleNamespace(name="UF_STATUS", enum_id_to_value={"68": "Принято"}),
                responder=SimpleNamespace(name="UF_RESPONDER"),
            )

        async def update_deal(self, deal_id, fields):
            calls.append((deal_id, fields))

        async def add_timeline_comment(self, deal_id, text):
            calls.append((deal_id, text))

    async def fake_answer(_callback_id, _text=""):
        pass

    monkeypatch.setattr(main, "BitrixClient", SuccessfulBitrix)
    monkeypatch.setattr(main, "answer_callback", fake_answer)
    with TestClient(app) as client:
        db.create_request("nested-callback", "5", "2")
        response = client.post(
            "/api/max/webhook",
            headers={"X-Max-Bot-Api-Secret": "max-secret"},
            json={
                "update_type": "message_callback",
                "updates": [{
                    "callback": {"callback_id": "cb-2", "payload": "accept:nested-callback"},
                }],
                "user": {"id": "77", "display_name": "Petr"},
            },
        )
    assert response.json() == {"status": "processed"}
    assert calls == [
        ("5", {"UF_STATUS": "68", "UF_RESPONDER": "Petr"}),
        ("5", "MAX: сообщение принято. Ответил: Petr."),
    ]


async def fake_prepared_deal(_deal_id="6"):
    return main.DealData("6", "Тест", "1", [{"id": 136}], "Не отправлено"), "chat-1", None, SimpleNamespace(), SimpleNamespace()


def test_bitrix_send_gets_deal_and_returns_request(monkeypatch):
    monkeypatch.setattr(main, "prepare_deal", fake_prepared_deal)
    with TestClient(app) as client:
        response = client.post(
            "/api/bitrix/send?deal_id=6",
            headers={"X-Bitrix-Token": "bitrix-secret"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["deal_id"] == "6"
    assert response.json()["recipient"] == "1"


def test_bitrix_send_accepts_json_deal_id(monkeypatch):
    monkeypatch.setattr(main, "prepare_deal", fake_prepared_deal)
    with TestClient(app) as client:
        response = client.post(
            "/api/bitrix/send",
            headers={"X-Bitrix-Token": "bitrix-secret", "Content-Type": "application/json"},
            json={"deal_id": "8"},
        )
    assert response.status_code == 200
    assert response.json()["deal_id"] == "8"


def test_bitrix_send_rejects_invalid_deal_id():
    with TestClient(app) as client:
        response = client.post(
            "/api/bitrix/send?deal_id=abc&text=Test&recipient=1&image_id=137",
            headers={"X-Bitrix-Token": "bitrix-secret"},
        )
    assert response.status_code == 422


def test_bitrix_client_requests_deal_and_metadata(monkeypatch):
    from app.bitrix import BitrixClient

    calls = []

    async def fake_call(method, params):
        calls.append((method, params))
        if method == "crm.item.get":
            return {"item": {"id": 6}}
        return {"fields": {"recipient": {"items": [{"ID": 60, "VALUE": "1"}]}}}

    client = BitrixClient()
    monkeypatch.setattr(client, "call", fake_call)
    import asyncio

    assert asyncio.run(client.get_deal("6")) == {"id": 6}
    assert asyncio.run(client.get_fields()) == {"recipient": {"items": [{"ID": 60, "VALUE": "1"}]}}
    assert calls[0] == ("crm.item.get", {"entityTypeId": 2, "id": 6, "useOriginalUfNames": "Y"})


def test_enum_mapping():
    from app.bitrix import BitrixClient

    assert BitrixClient.enum_map({"items": [{"ID": 60, "VALUE": "1"}, {"ID": 62, "VALUE": "2"}]}) == {"60": "1", "62": "2"}


def test_field_map_resolves_titles(monkeypatch):
    import app.bitrix as bitrix_module
    from app.bitrix import BitrixClient

    bitrix_module._field_map_cache = None
    async def fake_fields(self):
        return {
            "UF_TEXT": {"type": "string", "title": "Текст для MAX"},
            "UF_IMAGE": {"type": "file", "title": "Изображение для MAX"},
            "UF_RECIPIENT": {"type": "enumeration", "title": "Получатель MAX", "items": [{"ID": "60", "VALUE": "1"}]},
            "UF_STATUS": {"type": "enumeration", "title": "Статус отправки в MAX", "items": [{"ID": "66", "VALUE": "Отправлено"}]},
            "UF_RESPONDER": {"type": "string", "title": "Ответил в MAX"},
        }

    monkeypatch.setattr(BitrixClient, "get_fields", fake_fields)
    import asyncio

    field_map = asyncio.run(BitrixClient().get_field_map())
    assert field_map.text.name == "UF_TEXT"
    assert field_map.recipient.enum_id_to_value == {"60": "1"}


def test_download_file_uses_url_machine_without_logging_url(monkeypatch):
    from app.bitrix import BitrixClient

    class Response:
        content = b"image-bytes"
        headers = {"content-type": "image/png"}

        def raise_for_status(self):
            pass

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, url):
            assert url == "https://portal.example/file"
            return Response()

    monkeypatch.setattr("httpx.AsyncClient", lambda **_: Client())
    import asyncio

    result = asyncio.run(BitrixClient().download_file({"id": 136, "urlMachine": "https://portal.example/file"}))
    assert result.file_id == "136"
    assert result.content == b"image-bytes"
    assert result.content_type == "image/png"


def test_max_documented_callback_shape_updates_bitrix(monkeypatch):
    calls = []

    class SuccessfulBitrix:
        async def get_field_map(self):
            return SimpleNamespace(
                status=SimpleNamespace(name="UF_STATUS", enum_id_to_value={"69": "Отказано"}),
                responder=SimpleNamespace(name="UF_RESPONDER"),
            )

        async def update_deal(self, deal_id, fields):
            calls.append((deal_id, fields))

        async def add_timeline_comment(self, deal_id, text):
            calls.append((deal_id, text))

    async def fake_answer(_callback_id, _text=""):
        pass

    monkeypatch.setattr(main, "BitrixClient", SuccessfulBitrix)
    monkeypatch.setattr(main, "answer_callback", fake_answer)
    with TestClient(app) as client:
        db.create_request("documented-callback", "9", "2")
        response = client.post(
            "/api/max/webhook",
            headers={"X-Max-Bot-Api-Secret": "max-secret"},
            json={
                "update_type": "message_callback",
                "timestamp": 1,
                "callback": {
                    "timestamp": 1,
                    "callback_id": "cb-9",
                    "payload": "reject:documented-callback",
                    "user": {"user_id": 55, "name": "Вася Пупкин", "is_bot": False},
                },
                "message": {"body": {"mid": "mid-1"}},
            },
        )
    assert response.json() == {"status": "processed"}
    assert calls == [
        ("9", {"UF_STATUS": "69", "UF_RESPONDER": "Вася Пупкин"}),
        ("9", "MAX: сообщение отказано. Ответил: Вася Пупкин."),
    ]


def test_batched_updates_envelope_without_update_type(monkeypatch):
    calls = []

    class SuccessfulBitrix:
        async def get_field_map(self):
            return SimpleNamespace(
                status=SimpleNamespace(name="UF_STATUS", enum_id_to_value={"68": "Принято"}),
                responder=SimpleNamespace(name="UF_RESPONDER"),
            )

        async def update_deal(self, deal_id, fields):
            calls.append((deal_id, fields))

        async def add_timeline_comment(self, deal_id, text):
            calls.append((deal_id, text))

    async def fake_answer(_callback_id, _text=""):
        pass

    monkeypatch.setattr(main, "BitrixClient", SuccessfulBitrix)
    monkeypatch.setattr(main, "answer_callback", fake_answer)
    with TestClient(app) as client:
        db.create_request("batched-callback", "10", "2")
        response = client.post(
            "/api/max/webhook",
            headers={"X-Max-Bot-Api-Secret": "max-secret"},
            json={
                "updates": [
                    {
                        "update_type": "message_callback",
                        "callback": {
                            "callback_id": "cb-10",
                            "payload": "accept:batched-callback",
                            "user": {"user_id": 56, "name": "Иван"},
                        },
                    }
                ],
                "marker": 123,
            },
        )
    assert response.json() == {"status": "processed"}
    assert calls == [
        ("10", {"UF_STATUS": "68", "UF_RESPONDER": "Иван"}),
        ("10", "MAX: сообщение принято. Ответил: Иван."),
    ]


def test_webhook_without_secret_header_is_rejected():
    with TestClient(app) as client:
        response = client.post("/api/max/webhook", json={"update_type": "message_callback"})
    assert response.status_code == 401
