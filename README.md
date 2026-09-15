# Bitrix24 → MAX

Небольшой сервис на FastAPI. Короче, что он делает:

- берёт ID сделки из Битрикса (когда нажали кнопку бизнес-процесса)
- сам идёт в Bitrix REST и вытаскивает актуальные данные по сделке
- ищет нужные поля не по ID, а по названию (так надёжнее, ID может слететь)
- достаёт текст, получателя и файл
- решает куда слать в MAX (какой чат/получатель)
- отправляет сообщение в MAX с кнопками "Принять"/"Отказать"
- ждёт ответ от MAX (callback)
- находит по request_id исходную сделку и записывает туда результат

Работает в Docker, наружу торчит через Nginx + HTTPS.

Я делал это более-менее сам разобравшись, так что если что-то не так - пишите, поправим.

---

## Как это всё связано (примерно)

```
Bitrix24 (юзер жмёт кнопку) 
   -> ручной бизнес-процесс сделки 
   -> исходящий вебхук передаёт ID сделки 
   -> POST /api/bitrix/send 
   -> идём в Bitrix REST за актуальной сделкой (crm.item.get) 
   -> берём текст / получателя / статус / файл 
   -> шлём в MAX API 
   -> юзер видит сообщение с кнопками 
   -> жмёт кнопку -> прилетает message_callback на /api/max/webhook 
   -> по request_id находим сделку в SQLite 
   -> обновляем сделку обратно в Bitrix
```

### Почему поля ищутся по названию, а не по ID

Тут важный момент. В Bitrix у пользовательских полей есть техническое имя типа `UF_CRM_123456789`. Проблема в том, что если поле удалить и создать заново с тем же названием - Bitrix может дать ему уже другой ID. То есть если хардкодить ID в конфиге, оно рано или поздно сломается.

Поэтому в `.env` мы храним не ID, а просто название поля (title), и при каждом запросе приложение само спрашивает у Bitrix (`crm.item.fields`), какое сейчас у этого названия ID, и работает с ним.

Из-за этого важно: **если вы поменяли структуру полей в Bitrix, проверьте, что названия точно совпадают с тем, что в `.env`**. Лишний пробел или другая буква - и поле не найдётся.

---

## 1. Настройка в Bitrix24

Тут нужны две разные штуки, они не заменяют друг друга:

1. Ручной бизнес-процесс (через приложение "Мультиполятор") - чтобы человек жал кнопку в сделке
2. Входящий вебхук - чтобы наш сервер сам мог читать/писать в сделку через REST API

### 1.1 Поля сделки

В сделке должны быть такие поля (названия можно поменять, но тогда поменяйте и в `.env`):

| Для чего | Название по умолчанию |
|---|---|
| Текст сообщения | `Текст для MAX` |
| Картинка | `Изображение для MAX` |
| Получатель | `Получатель MAX` |
| Статус отправки | `Статус отправки в MAX` |
| Кто ответил | `Ответил в MAX` |

```dotenv
BITRIX_TEXT_FIELD_TITLE=Текст для MAX
BITRIX_IMAGE_FIELD_TITLE=Изображение для MAX
BITRIX_RECIPIENT_FIELD_TITLE=Получатель MAX
BITRIX_STATUS_FIELD_TITLE=Статус отправки в MAX
BITRIX_RESPONDER_FIELD_TITLE=Ответил в MAX
```

Важно: не суйте сюда `UF_CRM_...` айдишники, только человеческие названия полей.

### 1.2 Ручной запуск через "Мультиполятор"

Отправка не автоматическая, её запускает человек кнопкой. Для этого:

- в Bitrix есть приложение "Мультиполятор", в карточке сделки должна быть кнопка запуска БП
- создаём бизнес-процесс для сущности "Сделка", тип запуска - **ручной** (не автоматический, галки автозапуска снять)

Логика простая:

```
Открыли сделку -> нажали кнопку "Мультиполятор" -> запустился БП 
-> БП знает ID сделки -> дергает наш сервер -> сервер сам всё остальное вычитывает
```

### Нода "Исходящий вебхук" в бизнес-процессе

URL: `https://YOUR-DOMAIN/api/bitrix/send`
Метод: `POST`

Обязательно передать ID сделки через переменную `{{ID}}`, например:

```
https://YOUR-DOMAIN/api/bitrix/send?deal_id={{ID}}
```

или если поля отдельные - `deal_id = {{ID}}`.

Для авторизации используем токен из `.env`:

```dotenv
BITRIX_INCOMING_TOKEN=<секрет>
```

Лучше передавать заголовком:

```
X-Bitrix-Token: <BITRIX_INCOMING_TOKEN>
```

если нода умеет только query - можно так: `?token=<BITRIX_INCOMING_TOKEN>`

### 1.3 Входящий вебхук Bitrix

Это отдельная штука, нужна серверу чтобы читать/писать сделки.

Приложения -> Разработчикам -> Другое -> Входящий вебхук. Права нужны: `CRM`.

Ссылку кладём в `.env`:

```dotenv
BITRIX_WEBHOOK_URL=https://YOUR-PORTAL.bitrix24.ru/rest/USER_ID/WEBHOOK_CODE/
```

Зачем: когда прилетает `deal_id`, сервер не полагается на то, что БП передал ему текст/получателя/файл - он сам идёт в Bitrix через `crm.item.get` и берёт актуальные данные. И потом, когда пользователь ответил в MAX, сервер снова идёт в Bitrix и обновляет сделку.

---

## 2. Переменные окружения

```bash
cp .env.example .env
chmod 600 .env
```

Вот что там должно быть (по минимуму):

```dotenv
DATABASE_PATH=./data/app.db

BITRIX_INCOMING_TOKEN=<секрет для запроса из БП>
BITRIX_WEBHOOK_URL=https://YOUR-PORTAL.bitrix24.ru/rest/USER_ID/WEBHOOK_CODE/

BITRIX_TEXT_FIELD_TITLE=Текст для MAX
BITRIX_IMAGE_FIELD_TITLE=Изображение для MAX
BITRIX_RECIPIENT_FIELD_TITLE=Получатель MAX
BITRIX_STATUS_FIELD_TITLE=Статус отправки в MAX
BITRIX_RESPONDER_FIELD_TITLE=Ответил в MAX

ALLOW_RESEND=false

BITRIX_SENT_STATUS_VALUE=Отправлено
BITRIX_ACCEPTED_STATUS_VALUE=Принято
BITRIX_REJECTED_STATUS_VALUE=Отказано

MAX_BOT_TOKEN=<токен бота MAX>
MAX_WEBHOOK_SECRET=<секрет webhook MAX>
MAX_WEBHOOK_URL=https://YOUR-DOMAIN/api/max/webhook
MAX_API_URL=https://platform-api2.max.ru

MAX_SEND_ENABLED=false

MAX_TARGET_TYPE=chat
MAX_CHAT_ID=

MAX_RECIPIENT_ROUTES={}

REQUEST_ID_PREFIX=req_
CALLBACK_DELIMITER=:

ACCEPT_ACTION=accept
REJECT_ACTION=reject

ACCEPT_BUTTON_TEXT=Принять
REJECT_BUTTON_TEXT=Отказать

RESPONDER_INCLUDES_RESULT=false

REQUEST_TIMEOUT_SECONDS=15
```

Секреты можно сгенерить так:

```bash
openssl rand -hex 32
```

`.env` в git не коммитим, естественно.

---

## 3. Маршрутизация получателей в MAX

Если в поле "Получатель MAX" пишется имя человека, можно привязать его к конкретному чату в MAX:

```dotenv
MAX_TARGET_TYPE=chat
MAX_RECIPIENT_ROUTES={"Вася Пупкин":"-78058901422192","Петр Петров":"-78058901422193"}
```

Т.е. если написано "Вася Пупкин" - уйдёт в чат `-78058901422192`.

Если чат один общий на всех - проще:

```dotenv
MAX_TARGET_TYPE=chat
MAX_CHAT_ID=<chat-id>
```

---

## 4. Запуск на сервере

Нужен Linux сервер с Docker (Debian/Ubuntu + Docker + Compose plugin из офиц. репозитория).

```bash
docker --version
docker compose version
```

```bash
mkdir -p /opt/maxtest
cd /opt/maxtest
# сюда кладём проект
mkdir -p data
```

`docker-compose.yml` (уже в проекте):

```yaml
services:
  app:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

Запуск:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app
curl -fsS http://127.0.0.1:8000/health
```

Если health отвечает ок - всё завелось.

---

## 5. Nginx + HTTPS

Порт 8000 наружу светить не надо, всё через nginx на 443.

```
Internet -> https://YOUR-DOMAIN -> Nginx :443 -> 127.0.0.1:8000 -> Docker/FastAPI
```

Nginx должен проксировать `/api/bitrix/send` и `/api/max/webhook` на `http://127.0.0.1:8000`.

Пример конфига:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name YOUR-DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

Дальше вешаем Let's Encrypt, проверяем:

```bash
curl -fsS https://YOUR-DOMAIN/health
```

---

## 6. Webhook MAX

Для кнопок нужен внешний HTTPS endpoint: `https://YOUR-DOMAIN/api/max/webhook`

В MAX должна быть подписка на событие `message_callback`, секрет подписки = `MAX_WEBHOOK_SECRET` из `.env`.

Секрет - только `A-Z a-z 0-9 _ -`, длина 5-256 символов.

Если поменяли домен/https/секрет - подписку надо перепроверить.

---

## 7. Как это работает целиком

**Отправка:**

1. Открыли сделку, нажали "Мультиполятор"
2. Запустился ручной БП
3. БП стучится в `/api/bitrix/send` с `{{ID}}`
4. Сервер проверяет токен
5. Идёт в Bitrix REST за актуальной сделкой
6. Находит поля по названиям
7. Генерит `request_id`, сохраняет связь request_id -> deal_id -> получатель/чат
8. Шлёт сообщение в MAX

**Ответ:**

1. Юзер жмёт "Принять" или "Отказать" в MAX
2. Прилетает `message_callback` на `/api/max/webhook`
3. Сервер по `request_id` понимает, какая это сделка и какое действие
4. Обновляет сделку в Bitrix (статус + кто ответил)

---

## 8. Проверка после деплоя

```bash
docker compose ps
docker compose logs --tail=200 app
docker compose logs -f app   # смотреть в реальном времени
curl -fsS https://YOUR-DOMAIN/health
```

Дальше открываем сделку в Bitrix, жмём "Мультиполятор" - в логах должен появиться `POST /api/bitrix/send`.

---

## 9. Если поле не находится

Ошибка типа `Bitrix field not found by title` - проверяем по порядку:

1. поле реально существует
2. оно именно для сущности "Сделка"
3. название 1-в-1 совпадает с `.env` (пробелы, регистр и т.п.)
4. нет двух полей с одинаковым названием
5. у входящего вебхука есть право `CRM`

Не надо чинить это через `UF_CRM_...` - вся суть сервиса в том, что он ищет поле по названию сам.

---

## 10. Обновление / рестарт

Поменялся код:

```bash
cd /opt/maxtest
docker compose up -d --build --force-recreate
```

Поменялся только `.env`:

```bash
docker compose up -d --force-recreate
```

Просто рестарт:

```bash
docker compose restart app
```

---

## 11. Бэкап базы

SQLite лежит тут: `/opt/maxtest/data/app.db`

```bash
mkdir -p backups
sqlite3 data/app.db ".backup backups/app-$(date +%Y%m%d-%H%M%S).db"
```

Папку `data/` не удалять при обновлениях.

---

## 12. Безопасность (важно, не игнорить)

Никогда никуда не публикуем:

- `.env`
- `MAX_BOT_TOKEN`
- `MAX_WEBHOOK_SECRET`
- `BITRIX_INCOMING_TOKEN`
- `BITRIX_WEBHOOK_URL`

```bash
chmod 600 .env
```

В git, README, скриншоты, публичные логи - реальные токены не вставляем. Если секрет всё же засветился - отзываем и делаем новый.

---

## 13. Чек-лист для нового сервера

- [ ] SSH доступ есть
- [ ] Docker установлен
- [ ] Проект в `/opt/maxtest`
- [ ] Есть `data/`
- [ ] Есть `.env`
- [ ] `BITRIX_WEBHOOK_URL` настроен
- [ ] Входящий вебхук в Bitrix создан, право `CRM` есть
- [ ] Поля сделки созданы, названия совпадают с `.env`
- [ ] В "Мультиполятор" есть ручной БП для сделки
- [ ] Автозапуск БП выключен
- [ ] Нода "Исходящий вебхук" настроена, дергает `/api/bitrix/send` с `{{ID}}`
- [ ] `BITRIX_INCOMING_TOKEN` передаётся
- [ ] Контейнер стартует без ошибок
- [ ] `/health` отвечает
- [ ] DNS настроен
- [ ] Nginx + HTTPS работают
- [ ] MAX webhook смотрит на `/api/max/webhook`, подписка на `message_callback` есть
- [ ] `MAX_WEBHOOK_SECRET` совпадает
- [ ] Токен бота MAX верный
- [ ] `MAX_RECIPIENT_ROUTES` настроен (если нужна маршрутизация)
- [ ] Тестовая сделка реально доходит до MAX
- [ ] Кнопки "Принять"/"Отказать" обновляют сделку обратно
- [ ] Бэкап SQLite настроен

---

## 14. Диагностика проблем

**Контейнер не стартует** - `docker compose logs --tail=200 app`

**Bitrix ругается** - проверить `BITRIX_WEBHOOK_URL`, `BITRIX_INCOMING_TOKEN`, право `CRM` у вебхука

**Поле не находится** - см. пункт 9 выше

**БП не дёргает сервер** - проверить: приложение "Мультиполятор", сущность "Сделка", ручной запуск, автоматика выключена, нода вебхука настроена правильно, `{{ID}}` передаётся, токен передаётся

**MAX не получает сообщение** - смотрим логи, проверяем `MAX_BOT_TOKEN`, `MAX_SEND_ENABLED`, `MAX_TARGET_TYPE`, `MAX_CHAT_ID`, `MAX_RECIPIENT_ROUTES`

**Кнопки в MAX не работают** - проверяем `MAX_WEBHOOK_URL`, `MAX_WEBHOOK_SECRET`, подписку `message_callback`, что вебхук реально доступен снаружи по HTTPS. Смотрим логи, после клика должен прилетать `POST /api/max/webhook`.

---

## 15. Что пока не сделано (MVP же)

- данные лежат в SQLite, миграций схемы пока нет
- очереди/рейтлимита для MAX пока нет
- загрузка картинок в MAX зависит от того, как именно устроено файловое поле в Bitrix - это отдельная тема, пока не доделано полностью
