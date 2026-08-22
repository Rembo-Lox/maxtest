# Bitrix24 → MAX

Прослойка на FastAPI, которая:

1. получает ID сделки из ручного бизнес-процесса Bitrix24;
2. самостоятельно запрашивает актуальную сделку через Bitrix REST;
3. находит нужные пользовательские поля **по их названию**, а не по постоянному ID поля;
4. извлекает текст, получателя и данные файла;
5. выбирает нужный чат/получателя MAX;
6. отправляет сообщение в MAX с кнопками;
7. принимает `message_callback` от MAX;
8. по `request_id` находит исходную сделку и записывает результат ответа обратно в Bitrix24.

Проект рассчитан на запуск в Docker и публикацию наружу через Nginx + HTTPS.

---

## 1. Архитектура

```text
Bitrix24
   │
   │ ручная кнопка бизнес-процесса
   │
   ▼
Приложение «Мультиполятор»
   │
   │ Бизнес-процесс сделки
   │ ручной запуск
   │ нода «Исходящий вебхук»
   │ передаёт {{ID}}
   ▼
POST /api/bitrix/send
   │
   │ Bitrix REST
   ▼
crm.item.get
   │
   ├── текст
   ├── получатель
   ├── статус
   └── файл
   │
   ▼
MAX API
   │
   ▼
Сообщение + кнопки «Принять» / «Отказать»
   │
   │ message_callback
   ▼
POST /api/max/webhook
   │
   │ request_id
   ▼
SQLite
   │
   │ deal_id
   ▼
Bitrix REST
   │
   ▼
Обновление исходной сделки
```

### Важный принцип работы с полями Bitrix

Приложение **не должно хранить `UF_CRM_...` ID пользовательских полей в конфигурации**.

В `.env` задаются названия полей:

```dotenv
BITRIX_TEXT_FIELD_TITLE=Текст для MAX
BITRIX_IMAGE_FIELD_TITLE=Изображение для MAX
BITRIX_RECIPIENT_FIELD_TITLE=Получатель MAX
BITRIX_STATUS_FIELD_TITLE=Статус отправки в MAX
BITRIX_RESPONDER_FIELD_TITLE=Ответил в MAX
```

При работе приложение получает актуальную metadata сделки через `crm.item.fields` и сопоставляет поле с его `title`.

Это важно, потому что при удалении пользовательского поля и создании нового с тем же названием Bitrix24 может назначить ему другой внутренний ID. Приложение должно продолжать работать без ручной замены `UF_CRM_...`.

**После изменения структуры полей обязательно проверьте, что все поля из `.env` действительно существуют в Bitrix24 и имеют точно такие названия.**

---

# 2. Что нужно настроить в Bitrix24

Для проекта используются **два разных механизма Bitrix24**:

- ручной бизнес-процесс через приложение **«Мультиполятор»** — чтобы пользователь кнопкой запускал отправку;
- **входящий вебхук** — чтобы сервер мог самостоятельно читать и изменять сделку через Bitrix REST API.

Они не заменяют друг друга.

---

## 2.1. Пользовательские поля сделки

В сделке Bitrix24 должны существовать поля, соответствующие настройкам:

| Назначение | Название по умолчанию |
|---|---|
| Текст сообщения | `Текст для MAX` |
| Изображение | `Изображение для MAX` |
| Получатель | `Получатель MAX` |
| Статус отправки | `Статус отправки в MAX` |
| Пользователь, ответивший в MAX | `Ответил в MAX` |

Названия можно изменить, но тогда их нужно изменить и в `.env`.

Например:

```dotenv
BITRIX_TEXT_FIELD_TITLE=Текст для MAX
BITRIX_IMAGE_FIELD_TITLE=Изображение для MAX
BITRIX_RECIPIENT_FIELD_TITLE=Получатель MAX
BITRIX_STATUS_FIELD_TITLE=Статус отправки в MAX
BITRIX_RESPONDER_FIELD_TITLE=Ответил в MAX
```

### Не переносите в `.env` значения вида:

```text
UF_CRM_123456789
UF_CRM_987654321
```

Если поле было удалено и создано заново, его внутренний ID может измениться. Приложение должно найти его заново по названию.

---

# 3. Ручной запуск через «Мультиполятор»

В текущей схеме отправка сообщения запускается **не автоматически при изменении сделки**, а вручную пользователем через кнопку бизнес-процесса.

Используется приложение Bitrix24 **«Мультиполятор»**.

В карточке сделки должна быть доступна кнопка запуска бизнес-процесса.

## Настройка бизнес-процесса

Создайте бизнес-процесс для сущности:

```text
Сущность: Сделка
Бизнес-процесс: ручной запуск
```

Автоматический запуск не используется.

Если в настройках есть галки автоматического запуска/автоматизации, их нужно снять.

Идея следующая:

```text
Пользователь открыл сделку
        ↓
Нажал кнопку «Мультиполятор»
        ↓
Запустился ручной БП
        ↓
БП получил ID текущей сделки
        ↓
БП вызывает нашу прослойку
        ↓
Прослойка сама читает сделку через Bitrix REST
```

---

## 3.1. Нода исходящего вебхука

Внутри бизнес-процесса используется нода **«Исходящий вебхук»**.

URL обработчика:

```text
https://YOUR-DOMAIN/api/bitrix/send
```

Метод:

```text
POST
```

В запрос обязательно передаётся ID текущей сделки.

Используйте переменную Bitrix:

```text
{{ID}}
```

То есть в handler/query-параметр должен попасть ID текущей сделки.

Например:

```text
https://YOUR-DOMAIN/api/bitrix/send?deal_id={{ID}}
```

Если в интерфейсе ноды параметры задаются отдельно, передайте:

```text
deal_id = {{ID}}
```

### Авторизация

В проекте используется секрет:

```dotenv
BITRIX_INCOMING_TOKEN=<секрет>
```

Его необходимо передать приложению вместе с запросом.

Предпочтительный вариант — заголовок:

```http
X-Bitrix-Token: <BITRIX_INCOMING_TOKEN>
```

Если конкретная конфигурация ноды позволяет только query-параметры, поддерживается вариант:

```text
?token=<BITRIX_INCOMING_TOKEN>
```

Секрет должен совпадать со значением `BITRIX_INCOMING_TOKEN` на сервере.

---

# 4. Входящий вебхук Bitrix24

Теперь создаётся **отдельный входящий вебхук**, который используется уже не бизнес-процессом, а сервером.

В Bitrix24 откройте:

```text
Приложения
→ Разработчикам
→ Другое
→ Входящий вебхук
```

Создайте входящий вебхук.

Для него нужны права:

```text
CRM
```

Скопируйте URL созданного вебхука и поместите его в `.env`:

```dotenv
BITRIX_WEBHOOK_URL=https://YOUR-PORTAL.bitrix24.ru/rest/USER_ID/WEBHOOK_CODE/
```

### Зачем нужен этот вебхук

Когда `/api/bitrix/send` получает:

```text
deal_id=123
```

сервер **не ожидает, что бизнес-процесс передаст ему весь текст сделки, получателя и файл**.

Он сам обращается в Bitrix:

```text
crm.item.get
```

и получает актуальное состояние сделки.

Это принципиально важно: бизнес-процесс передаёт только идентификатор сделки, а данные берутся напрямую из Bitrix24.

После ответа пользователя в MAX сервер снова обращается к Bitrix REST и обновляет нужную сделку.

---

# 5. Переменные окружения

Создайте `.env` на сервере:

```bash
cp .env.example .env
chmod 600 .env
```

Минимальная конфигурация:

```dotenv
DATABASE_PATH=./data/app.db

BITRIX_INCOMING_TOKEN=<секрет-для-входящего-запроса-из-БП>
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

MAX_BOT_TOKEN=<токен-бота-MAX>
MAX_WEBHOOK_SECRET=<секрет-webhook-MAX>
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

Секреты генерируйте отдельно:

```bash
openssl rand -hex 32
```

Не коммитьте `.env` в Git.

---

# 6. Маршрутизация получателей MAX

Если поле `Получатель MAX` содержит имя человека, можно сопоставить его с конкретным MAX chat ID.

Например:

```dotenv
MAX_TARGET_TYPE=chat
MAX_RECIPIENT_ROUTES={"Вася Пупкин":"-78058901422192","Петр Петров":"-78058901422193"}
```

Тогда:

```text
Получатель MAX = Вася Пупкин
```

приведёт к отправке в:

```text
-78058901422192
```

Если используется один общий чат:

```dotenv
MAX_TARGET_TYPE=chat
MAX_CHAT_ID=<chat-id>
```

---

# 7. Установка сервера

Инструкция рассчитана на Linux-сервер с Docker.

Для Debian/Ubuntu установите Docker и Compose plugin из официального репозитория Docker.

Проверьте:

```bash
docker --version
docker compose version
```

Создайте каталог:

```bash
mkdir -p /opt/maxtest
cd /opt/maxtest
```

Разместите проект в этом каталоге.

Создайте каталог данных:

```bash
mkdir -p data
```

---

# 8. Запуск Docker

В проекте используется:

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

Первый запуск:

```bash
docker compose up -d --build
```

Проверка:

```bash
docker compose ps
docker compose logs --tail=100 app
```

Проверка приложения:

```bash
curl -fsS http://127.0.0.1:8000/health
```

Ожидается успешный HTTP-ответ.

---

# 9. Nginx и HTTPS

Внешний доступ к приложению должен идти через HTTPS.

Схема:

```text
Internet
   ↓
https://YOUR-DOMAIN
   ↓
Nginx :443
   ↓
127.0.0.1:8000
   ↓
Docker / FastAPI
```

Порт `8000` не требуется публиковать наружу для production-схемы.

Nginx должен проксировать:

```text
/api/bitrix/send
/api/max/webhook
```

на:

```text
http://127.0.0.1:8000
```

Пример:

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

После настройки DNS установите сертификат Let's Encrypt и включите HTTPS.

Проверьте:

```bash
curl -fsS https://YOUR-DOMAIN/health
```

---

# 10. MAX webhook

Для callback-кнопок MAX нужен внешний HTTPS endpoint:

```text
https://YOUR-DOMAIN/api/max/webhook
```

В MAX должна существовать webhook-подписка с событием:

```text
message_callback
```

Секрет:

```dotenv
MAX_WEBHOOK_SECRET=<секрет>
```

должен совпадать с секретом подписки.

Используйте только допустимые символы:

```text
A-Z
a-z
0-9
_
-
```

и длину от 5 до 256 символов.

После изменения домена, HTTPS или секрета проверьте подписку MAX.

---

# 11. Полный сценарий работы

## Отправка

```text
1. Пользователь открывает сделку.
2. Нажимает кнопку «Мультиполятор».
3. Запускается ручной бизнес-процесс сделки.
4. БП вызывает /api/bitrix/send.
5. В запросе передаётся {{ID}} текущей сделки.
6. Прослойка проверяет секрет.
7. Прослойка вызывает Bitrix REST.
8. Получает актуальную сделку.
9. Находит пользовательские поля по названиям.
10. Формирует request_id.
11. Сохраняет связь request_id → deal_id → recipient/chat_id.
12. Отправляет сообщение в MAX.
```

## Ответ

```text
1. Пользователь нажимает «Принять» или «Отказать» в MAX.
2. MAX отправляет message_callback.
3. /api/max/webhook принимает callback.
4. Прослойка определяет request_id и действие.
5. По request_id находится исходная сделка.
6. Через Bitrix REST обновляется сделка.
7. В статус записывается результат.
8. В «Ответил в MAX» записывается пользователь MAX.
```

---

# 12. Проверка после деплоя

Проверить контейнер:

```bash
docker compose ps
```

Логи:

```bash
docker compose logs --tail=200 app
```

Следить в реальном времени:

```bash
docker compose logs -f app
```

Healthcheck:

```bash
curl -fsS https://YOUR-DOMAIN/health
```

Проверка исходящего webhook из Bitrix:

```bash
docker compose logs -f app
```

Затем в Bitrix откройте сделку и нажмите кнопку **«Мультиполятор»**.

В логах должен появиться запрос к:

```text
POST /api/bitrix/send
```

---

# 13. Важная диагностика Bitrix-полей

Если после изменения полей Bitrix появляется ошибка:

```text
Bitrix field not found by title
```

проверьте:

1. поле действительно существует;
2. оно создано именно для сущности «Сделка»;
3. название поля точно совпадает с `.env`;
4. нет двух полей с одинаковым названием;
5. входящий вебхук имеет право `CRM`;
6. приложение получает актуальную metadata Bitrix.

Например, если в `.env` указано:

```dotenv
BITRIX_TEXT_FIELD_TITLE=Текст для MAX
```

в Bitrix должно существовать поле с точным названием:

```text
Текст для MAX
```

Не пытайтесь исправлять проблему заменой названия на `UF_CRM_...`: приложение специально построено так, чтобы разрешать поле по названию.

---

# 14. Обновление проекта

Если изменился код:

```bash
cd /opt/maxtest
docker compose up -d --build --force-recreate
```

Проверить:

```bash
docker compose ps
docker compose logs --tail=100 app
```

Если изменился только `.env`:

```bash
docker compose up -d --force-recreate
```

Если нужно просто перезапустить:

```bash
docker compose restart app
```

---

# 15. Резервная копия базы

SQLite находится в:

```text
/opt/maxtest/data/app.db
```

Перед обновлением можно сделать backup:

```bash
mkdir -p backups

sqlite3 data/app.db \
  ".backup backups/app-$(date +%Y%m%d-%H%M%S).db"
```

Не удаляйте каталог:

```text
data/
```

при обычном обновлении проекта.

---

# 16. Безопасность

Никогда не публикуйте:

```text
.env
MAX_BOT_TOKEN
MAX_WEBHOOK_SECRET
BITRIX_INCOMING_TOKEN
BITRIX_WEBHOOK_URL
```

`.env` должен иметь права:

```bash
chmod 600 .env
```

Не вставляйте реальные токены в Git, README, скриншоты или публичные логи.

Если секрет уже был опубликован, его следует отозвать и создать новый.

---

# 17. Быстрый чек-лист нового развёртывания

- [ ] Сервер доступен по SSH.
- [ ] Docker установлен.
- [ ] Проект размещён в `/opt/maxtest`.
- [ ] Создан `data/`.
- [ ] Создан `.env`.
- [ ] Настроен `BITRIX_WEBHOOK_URL`.
- [ ] Создан входящий вебхук Bitrix24.
- [ ] Входящему вебхуку выдано право `CRM`.
- [ ] В Bitrix24 созданы все необходимые поля сделки.
- [ ] Названия полей совпадают с `BITRIX_*_FIELD_TITLE`.
- [ ] В приложении «Мультиполятор» создан ручной бизнес-процесс для сущности «Сделка».
- [ ] Автоматический запуск бизнес-процесса отключён.
- [ ] В БП добавлена нода «Исходящий вебхук».
- [ ] Handler указывает на `/api/bitrix/send`.
- [ ] В handler передаётся `{{ID}}` текущей сделки.
- [ ] Передаётся `BITRIX_INCOMING_TOKEN`.
- [ ] Docker-контейнер запускается без ошибок.
- [ ] `/health` отвечает успешно.
- [ ] DNS указывает на сервер.
- [ ] Nginx настроен.
- [ ] HTTPS работает.
- [ ] MAX webhook указывает на `/api/max/webhook`.
- [ ] MAX subscription содержит `message_callback`.
- [ ] `MAX_WEBHOOK_SECRET` совпадает с секретом подписки.
- [ ] MAX bot token корректный.
- [ ] `MAX_RECIPIENT_ROUTES` настроен, если используется маршрутизация по получателю.
- [ ] Тестовая сделка успешно отправляется в MAX.
- [ ] Кнопка «Принять» обновляет исходную сделку.
- [ ] Кнопка «Отказать» обновляет исходную сделку.
- [ ] В поле «Ответил в MAX» появляется пользователь.
- [ ] SQLite backup настроен.

---

# 18. Диагностика

### Приложение не запускается

```bash
docker compose logs --tail=200 app
```

### Bitrix возвращает ошибку

Проверьте:

```text
BITRIX_WEBHOOK_URL
BITRIX_INCOMING_TOKEN
```

и наличие права:

```text
CRM
```

у входящего вебхука.

### Не находится поле

Проверьте точное название поля в Bitrix24 и соответствующее:

```dotenv
BITRIX_*_FIELD_TITLE
```

### Бизнес-процесс не вызывает приложение

Проверьте:

- приложение «Мультиполятор»;
- сущность «Сделка»;
- ручной запуск;
- отключённую автоматику;
- ноду «Исходящий вебхук»;
- URL `/api/bitrix/send`;
- передачу `{{ID}}`;
- токен авторизации.

### MAX не получает сообщение

Проверьте:

```bash
docker compose logs --tail=200 app
```

и:

```text
MAX_BOT_TOKEN
MAX_SEND_ENABLED
MAX_TARGET_TYPE
MAX_CHAT_ID
MAX_RECIPIENT_ROUTES
```

### Кнопки MAX ничего не делают

Проверьте:

```text
MAX_WEBHOOK_URL
MAX_WEBHOOK_SECRET
```

и наличие подписки:

```text
message_callback
```

Webhook должен быть доступен из интернета по HTTPS/443.

Проверяйте логи:

```bash
docker compose logs -f app
```

После нажатия кнопки должен появиться запрос:

```text
POST /api/max/webhook
```

---

# 19. Текущие ограничения MVP

На текущем этапе:

- данные запросов хранятся в SQLite;
- `request_id` используется для связывания сообщения MAX с исходной сделкой;
- строгая фоновая очередь для ограничения скорости MAX пока не реализована;
- полноценная обработка/загрузка изображения в MAX зависит от конкретной схемы файлового поля Bitrix24 и является отдельным этапом;
- миграции SQLite-схемы пока не используются.

