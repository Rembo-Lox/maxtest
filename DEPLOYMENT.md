# Деплой Bitrix24 -> MAX на Debian 11

Мануал для временного сервера `194.87.74.71` и домена `rembovrc.ru`.

## Важные ограничения

- IP можно использовать для проверки приложения и `/health`.
- Для production-подобного MAX webhook используйте `https://rembovrc.ru/api/max/webhook` или `https://www.rembovrc.ru/api/max/webhook`.
- MAX требует HTTPS на порту 443 и доверенный сертификат. Самоподписанный сертификат не подойдет.
- Не передавайте токены в командах, истории shell или git.
- Токен MAX, который ранее был опубликован в черновом файле, необходимо отозвать и заменить новым.

## 1. DNS

У регистратора создайте записи:

```text
A     rembovrc.ru       194.87.74.71
A     www.rembovrc.ru   194.87.74.71
```

Проверьте, что DNS уже обновился:

```bash
getent hosts rembovrc.ru
getent hosts www.rembovrc.ru
```

Обе записи должны указывать на текущий IP сервера. Если IP изменится, обновите A-записи и сертификат можно будет перевыпустить при необходимости.

## 2. Подключение к серверу

На локальном компьютере подключитесь к серверу:

```bash
ssh root@194.87.74.71
```

Сразу обновите Debian:

```bash
apt update
apt full-upgrade -y
apt install -y ca-certificates curl git ufw openssl
reboot
```

После перезагрузки подключитесь снова.

# Скачиваем корневой и промежуточный сертификаты Минцифры
curl -o /usr/local/share/ca-certificates/russian_trusted_root_ca.crt \
  https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt

curl -o /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt \
  https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt

# Обновляем хранилище доверенных сертификатов
update-ca-certificates

## 3. Базовая настройка firewall

Для временного тестового сервера работаем под `root`, без создания отдельного пользователя и настройки SSH-ключей. Не закрывайте текущую SSH-сессию во время настройки.

Разрешите только SSH, HTTP и HTTPS:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose
```

Настройку отдельного пользователя и SSH-ключей для этого временного сервера пропускаем.

## 4. Установка Docker

Для Debian 11 установите Docker из официального репозитория Docker:

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
printf '%s\n' \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
  > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker --version
docker compose version
```

## 5. Передача проекта

### Вариант A: git

Если проект находится в доступном приватном/публичном Git-репозитории:

```bash
mkdir -p /opt/maxtest
cd /opt/maxtest
git clone <URL_РЕПОЗИТОРИЯ> .
```

### Вариант B: rsync с локального компьютера

Команду выполнять на локальном компьютере из корня проекта:

```bash
rsync -az --delete \
  --exclude .env \
  --exclude data/ \
  --exclude .pytest_cache/ \
  ./ root@194.87.74.71:/opt/maxtest/
```

На сервере:

```bash
mkdir -p /opt/maxtest/data
cd /opt/maxtest
```

Не используйте `--delete`, если в каталоге сервера есть файлы, созданные вручную и не хранящиеся в проекте.

## 6. Конфигурация секретов

На сервере создайте `.env` с ограниченными правами:

```bash
cd /opt/maxtest
cp .env.example .env
chmod 600 .env
```

Откройте файл редактором:

```bash
nano .env
```

Минимальная конфигурация:

```dotenv
DATABASE_PATH=./data/app.db
BITRIX_INCOMING_TOKEN=<длинный-случайный-токен-для-Bitrix>
BITRIX_WEBHOOK_URL=https://<ваш-портал>.bitrix24.ru/rest/<user>/<webhook>
BITRIX_TEXT_FIELD_TITLE=Текст для MAX
BITRIX_IMAGE_FIELD_TITLE=Изображение для MAX
BITRIX_RECIPIENT_FIELD_TITLE=Получатель MAX
BITRIX_STATUS_FIELD_TITLE=Статус отправки в MAX
BITRIX_RESPONDER_FIELD_TITLE=Ответил в MAX
ALLOW_RESEND=false
BITRIX_SENT_STATUS_VALUE=Отправлено
BITRIX_ACCEPTED_STATUS_VALUE=Принято
BITRIX_REJECTED_STATUS_VALUE=Отказано
MAX_BOT_TOKEN=<новый-токен-MAX>
MAX_WEBHOOK_SECRET=<секрет-длиной-5-256-символов>
MAX_API_URL=https://platform-api2.max.ru
MAX_SEND_ENABLED=false
MAX_TARGET_TYPE=user
MAX_CHAT_ID=
# Bitrix24 recipient name -> MAX chat_id; keep this as one line in .env
MAX_RECIPIENT_ROUTES={}
REQUEST_ID_PREFIX=req_
CALLBACK_DELIMITER=:
ACCEPT_ACTION=accept
REJECT_ACTION=reject
ACCEPT_BUTTON_TEXT=Принять
REJECT_BUTTON_TEXT=Отказать
REQUEST_TIMEOUT_SECONDS=15
```

Сгенерировать значения без вывода токена в историю shell можно так:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

В Bitrix24 должны существовать поля с именами из `BITRIX_STATUS_FIELD` и `BITRIX_RESPONDER_FIELD`. Если названия отличаются, укажите фактические `UF_CRM_...` поля.

Если Bitrix24 будет присылать имена адресатов, а у каждого адресата свой MAX-чат, настройте две пары, например:

```dotenv
MAX_TARGET_TYPE=chat
MAX_RECIPIENT_ROUTES={"Вася Пупкин":"-78058901422192","Петр Петров":"-78058901422193"}
```

В запросе Bitrix24 тогда передается имя:

```json
{"deal_id":"15427","text":"Тест","recipient":"Вася Пупкин"}
```

Сервис найдет `-78058901422192`, сохранит его в `recipient_id` для этого `request_id` и отправит сообщение в первый чат. Чтобы поменять адресата или чат, достаточно изменить `MAX_RECIPIENT_ROUTES` в `.env` и пересоздать контейнер:

```bash
docker compose up -d --force-recreate
```

## 7. Первый запуск без reverse proxy

Это нужно только для локальной проверки контейнера по IP:

```bash
cd /opt/maxtest
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app
```

Если изменили код или зависимости:

```bash
cd /opt/maxtest
docker compose up -d --build --force-recreate
docker compose ps
docker compose logs --tail=100 app
```



Проверка с сервера:

```bash
curl -fsS http://127.0.0.1:8000/health
```

Проверка извне:

```bash
curl -fsS http://194.87.74.71:8000/health
```

Порт `8000` не нужен для внешнего доступа после установки Nginx. Временно открыть его можно только для диагностики:

```bash
ufw allow 8000/tcp
```

После проверки удалите правило:

```bash
ufw delete allow 8000/tcp
```

## 8. Nginx reverse proxy

Установите Nginx:

```bash
apt install -y nginx
rm -f /etc/nginx/sites-enabled/default
nano /etc/nginx/sites-available/maxtest
```

Вставьте конфигурацию:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name rembovrc.ru www.rembovrc.ru;

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

Активируйте сайт и проверьте конфигурацию:

```bash
ln -s /etc/nginx/sites-available/maxtest /etc/nginx/sites-enabled/maxtest
nginx -t
systemctl enable --now nginx
systemctl reload nginx
curl -fsS http://rembovrc.ru/health
```

## 9. HTTPS через Let's Encrypt

Установите Certbot:

```bash
apt install -y certbot python3-certbot-nginx
```

Выпустите сертификат:

```bash
certbot --nginx -d rembovrc.ru -d www.rembovrc.ru
```

Выберите перенаправление HTTP на HTTPS, если Certbot предложит этот вариант.

Проверьте автоматическое продление:

```bash
certbot renew --dry-run
curl -fsS https://rembovrc.ru/health
```

## 10. Подписка MAX webhook

В MAX создайте/обновите подписку с URL:

```text
https://rembovrc.ru/api/max/webhook
```

В подписке укажите секрет, совпадающий с `MAX_WEBHOOK_SECRET`, и событие:

```json
{
  "url": "https://rembovrc.ru/api/max/webhook",
  "update_types": ["message_callback"],
  "secret": "<тот-же-MAX_WEBHOOK_SECRET>"
}
```

Запрос к MAX API выполняется с заголовком `Authorization: <MAX_BOT_TOKEN>`. Токен не передавайте в URL.

`MAX_WEBHOOK_SECRET` обязан соответствовать `^[A-Za-z0-9_-]{5,256}$`. Любой другой символ (`:`, `!`, `.`, `#` и подобные) приводит к `400 Bad Request` от `POST /subscriptions`: подписка не создаётся, `GET /subscriptions` возвращает `{"subscriptions":[]}`, и MAX никогда не доставляет `message_callback` — кнопки в чате выглядят нерабочими. При старте приложение пишет в лог ошибку, если секрет не подходит под этот шаблон.

Создать подписку с сервера, не вводя секреты руками:

```bash
cd /opt/maxtest
set -a; . ./.env; set +a
curl -sS -X POST 'https://platform-api2.max.ru/subscriptions' \
  -H "Authorization: $MAX_BOT_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"url\":\"https://rembovrc.ru/api/max/webhook\",\"update_types\":[\"message_callback\"],\"secret\":\"$MAX_WEBHOOK_SECRET\"}"
curl -sS 'https://platform-api2.max.ru/subscriptions' -H "Authorization: $MAX_BOT_TOKEN"
```

Ожидаемый ответ второй команды содержит вашу подписку с `message_callback`. Если подписка не отвечает 200 в течение 8 часов, MAX отписывает бота автоматически — после аварии подписку нужно создать заново.

## 11. Настройка ноды «Исходящий вебхук» в БП

Не используйте стандартный исходящий webhook Bitrix24 с событиями `OnCrmDealUpdate` или `OnCrmDealAdd`. В этом проекте запрос отправляет нода **«Исходящий вебхук»** последовательного бизнес-процесса, который запускается вручную кнопкой «Мультиполятор» в карточке сделки.

URL handler ноды:

```text
https://rembovrc.ru/api/bitrix/send
```

БП передает только ID текущей сделки. Текст, получатель и файл сервер получает сам через Bitrix REST:

```text
deal_id = ID текущей сделки
```

Основной вариант для этой ноды: `POST` или `GET` с единственным query-параметром `deal_id`.

В поле handler укажите только:

```text
https://rembovrc.ru/api/bitrix/send
```

Если нода требует JSON body, укажите только:

```json
{
  "deal_id": "{{ID текущей сделки}}"
}
```

Рекомендуемый handler URL:

```text
https://rembovrc.ru/api/bitrix/send?deal_id={{ID текущей сделки}}
```

Для защиты запроса нода должна передать заголовок `X-Bitrix-Token`, равный `BITRIX_INCOMING_TOKEN`. Если UI ноды не позволяет задавать заголовки, временно добавьте секрет в URL handler как query-параметр `token`:

```text
https://rembovrc.ru/api/bitrix/send?token=<BITRIX_INCOMING_TOKEN>&deal_id={{ID текущей сделки}}
```

Этот способ менее безопасен: URL может попасть в access-логи Nginx. Не оставляйте секрет в URL после теста, а при возможности настройте заголовок или отдельное ограничение доступа.

Цель первого теста: открыть карточку сделки, нажать «Мультиполятор», запустить БП и проверить, что сервер получил `deal_id`, затем через Bitrix REST прочитал `text`, `recipient` и `image_id`. При `MAX_SEND_ENABLED=false` запрос сохранится в SQLite, но сообщение в MAX не отправится.

## 12. Проверка endpoint Bitrix24

Команду выполнять на сервере или с локального компьютера, подставив токен без публикации его в git:

Для общего тестового чата задайте в `.env`:

```dotenv
MAX_TARGET_TYPE=chat
MAX_CHAT_ID=<изменяемый-chat-id>
```

Тогда можно отправлять запрос без `recipient`, только с `deal_id` и `text`. Для отдельной заявки передайте `chat_id` в JSON. Для личного диалога используйте `MAX_TARGET_TYPE=user` и `recipient`.

```bash
curl -i -X POST https://rembovrc.ru/api/bitrix/send \
  -H 'X-Bitrix-Token: <BITRIX_INCOMING_TOKEN>' \
  -G --data-urlencode 'deal_id=15427'
```

Ожидаемый ответ:

```json
{"status":"accepted","deal_id":"15427"}
```

Состояние контейнера и последние логи:

```bash
docker compose ps
docker compose logs --tail=200 app
sqlite3 /opt/maxtest/data/app.db 'select request_id, deal_id, recipient_id, status, created_at, answered_at from requests order by id desc limit 10;'
```

Проверка файла, полученного от БП:

```bash
sqlite3 /opt/maxtest/data/app.db 'select request_id, deal_id, recipient_id, image_id, status from requests order by id desc limit 10;'
```

Если `sqlite3` не установлен:

```bash
apt install -y sqlite3
```

## 13. Как применить изменения

Все команды выполнять на сервере:

```bash
cd /opt/maxtest
```

Если изменили только `.env`, например `MAX_RECIPIENT_ROUTES`, примените настройки так:

```bash
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=100 app
```

Если изменили Python-код, `Dockerfile`, `requirements.txt` или `docker-compose.yml`, пересоберите образ:

```bash
docker compose up -d --build --force-recreate
docker compose ps
docker compose logs --tail=100 app
```

Для текущей версии после обновления кода используйте именно этот вариант:

```bash
cd /opt/maxtest
docker compose up -d --build --force-recreate
docker compose logs --tail=100 app
```

Если ничего не меняли, а нужно просто перезапустить приложение:

```bash
docker compose restart app
```

Проверка после любого варианта:

```bash
curl -fsS http://127.0.0.1:8000/health
```

`.env` и каталог `data/` не удаляйте. Сохраненные в SQLite запросы после перезапуска не пропадут.

## 14. Обновление приложения

При обновлении через git:

```bash
cd /opt/maxtest
git pull --ff-only
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app
```

При обновлении через rsync повторите команду передачи проекта, затем:

```bash
cd /opt/maxtest
docker compose up -d --build
```

`.env` и каталог `data/` не должны удаляться при обновлении.

## 15. Остановка и диагностика

```bash
cd /opt/maxtest
docker compose logs -f app
docker compose restart app
docker compose down
systemctl status nginx --no-pager
ufw status verbose
```

### Проверка callback-кнопок MAX

После отправки сообщения нажмите «Принять» или «Отказать» и сразу проверьте логи:

```bash
docker compose logs --since=2m app | grep -E 'MAX callback|/api/max/webhook'
```

Ожидаемые записи:

```text
MAX callback received shape=...
MAX callback parsed action=accept request_id=... has_callback_id=True ...
```

Значения токенов и полный JSON события в логи не выводятся. Если записи `MAX callback received` нет, MAX не доставляет событие: проверьте URL webhook, HTTPS на порту 443 и подписку `message_callback`.

Проверить подписки можно через API MAX. Токен вводите через переменную окружения, чтобы не сохранить его в истории shell:

```bash
read -s MAX_TOKEN
curl -fsS 'https://platform-api2.max.ru/subscriptions' \
  -H "Authorization: $MAX_TOKEN"
unset MAX_TOKEN
```

В ответе должна быть подписка с URL вида `https://<ваш-домен>/api/max/webhook` и событием `message_callback`. После проверки обновите поле сделки в Bitrix: статус должен стать `Принято` или `Отказано`, а `Ответил в MAX` должен содержать имя или ID пользователя.

Если после нажатия кнопки в логах нет `MAX callback received`, пересоздайте подписку явно:

```bash
read -s MAX_TOKEN
curl -fsS -X POST 'https://platform-api2.max.ru/subscriptions' \
  -H "Authorization: $MAX_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://<ваш-домен>/api/max/webhook","update_types":["message_callback"],"secret":"<значение-MAX_WEBHOOK_SECRET>"}'
unset MAX_TOKEN
```

Перед этим удалите старую подписку через `DELETE /subscriptions/{subscription_id}`, если API вернуло существующую подписку с другим URL или без `message_callback`. Не передавайте токен в URL и не вставляйте его непосредственно в команду shell.

Во время проверки держите логи открытыми:

```bash
docker compose logs -f --since=1m app
```

На каждый callback должен появиться HTTP-запрос к `/api/max/webhook`. Код `401` означает несовпадение `MAX_WEBHOOK_SECRET`; отсутствие HTTP-запроса означает проблему подписки, URL, DNS или TLS webhook-сервера. Код `200` с `MAX callback ignored` означает, что пришёл callback с неподдерживаемой структурой; в этом случае пришлите только безопасную строку `shape` из лога, без JSON с токенами.

Частые причины ошибок:

- `401` от `/api/bitrix/send`: неверный `X-Bitrix-Token` или пустой `BITRIX_INCOMING_TOKEN`.
- `401` от `/api/max/webhook`: секрет заголовка не совпадает с `MAX_WEBHOOK_SECRET`.
- MAX не доставляет webhook: URL не HTTPS/не 443, DNS не указывает на сервер, сертификат недоверенный или подписка не содержит `message_callback`.
- запись получает `error`: MAX API недоступен, токен неверен или сервер не может проверить TLS-сертификат.
- Bitrix обновляется без полей: проверьте реальные имена пользовательских полей `UF_CRM_...`.

## 16. Резервная копия SQLite

Перед обновлениями делайте копию базы:

```bash
cd /opt/maxtest
mkdir -p backups
sqlite3 data/app.db ".backup backups/app-$(date +%Y%m%d-%H%M%S).db"
find backups -type f -mtime +14 -delete
```

## 17. Что пока не реализовано

- получение изображения из Bitrix24 по `image_id`;
- загрузка изображения через `POST /uploads` MAX и отправка image attachment;
- очередь фоновых задач для строгого ограничения MAX в 2 сообщения/секунду;
- миграции схемы базы данных.

Это отдельные следующие этапы MVP и не должны маскироваться настройками деплоя.
