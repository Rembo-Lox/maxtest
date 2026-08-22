# Bitrix24 -> MAX MVP

## Запуск

1. Скопируйте `.env.example` в `.env` и заполните секреты.
2. Установите зависимости: `python -m pip install -r requirements.txt`.
3. Запустите: `uvicorn app.main:app --reload`.

Docker: `docker compose up --build`.

Инструкция по деплою на Debian 11 и настройке Nginx/HTTPS: [DEPLOYMENT.md](DEPLOYMENT.md).

## Endpoints

- `GET` или `POST /api/bitrix/send?deal_id=6` с заголовком `X-Bitrix-Token`.
- `POST /api/max/webhook` с заголовком `X-Max-Bot-Api-Secret`.

`/api/bitrix/send` получает сделку через Bitrix REST `crm.item.get`, читает текст, enum-получателя и файл `urlMachine`, затем выбирает MAX-чат через `MAX_RECIPIENT_ROUTES`. JSON допускается только для передачи `deal_id`.

Для запуска БП используйте URL `https://rembovrc.ru/api/bitrix/send?token=<BITRIX_INCOMING_TOKEN>&deal_id=...`. Остальные поля сервер получает через `crm.item.get`.

`request_id` генерируется сервером как строка вида `req_<случайное-значение>`, сохраняется в SQLite и передается в callback. Сопоставление `request_id -> deal_id -> recipient/chat_id` не задается вручную в `.env`. Имя нажавшего пользователя, например `Вася Пупкин`, приходит от MAX в callback и сохраняется в `max_user_name`.

Если Bitrix24 присылает имя адресата, например `Вася Пупкин`, задайте маршруты в `.env`: `MAX_TARGET_TYPE=chat` и `MAX_RECIPIENT_ROUTES={"Вася Пупкин":"-780...","Петр Петров":"-781..."}`. Тогда значение `recipient` из входящего JSON выбирает нужный MAX `chat_id`. Для пользователя используйте `MAX_TARGET_TYPE=user` и `recipient` как ID пользователя.

Коды callback и подписи кнопок меняются через `ACCEPT_ACTION`, `REJECT_ACTION`, `ACCEPT_BUTTON_TEXT`, `REJECT_BUTTON_TEXT`. Подписка MAX должна включать событие `message_callback`, а URL webhook должен быть HTTPS на порту 443 за reverse proxy.

Поле `image_id` принято и сохранено на уровне контракта, но получение файла из Bitrix24 и загрузка в MAX оставлены следующим этапом: это требует конкретной схемы файлового поля/метода в вашем портале.
