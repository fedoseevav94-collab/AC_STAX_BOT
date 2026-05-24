# Запуск бота без привязки к ноутбуку

Лучший вариант: небольшой VPS/сервер с Docker. Бот будет работать постоянно и автоматически перезапускаться.

## 1. Подготовить сервер

На сервере должны быть установлены Docker и Docker Compose.

## 2. Скопировать проект на сервер

Скопируйте папку проекта на сервер любым удобным способом.

## 3. Создать `.env`

На сервере рядом с `docker-compose.yml` создайте `.env`:

```bash
BOT_TOKEN=telegram-token
WORK_CHAT_ID=
APPROVER_USERNAMES=sergey,stax_ru
ADMIN_USERNAMES=stax_ru
REPORT_USERNAMES=Fedos_AV,D_u_a
FREE_MODELS=JAC J7:10
DRIVER_RATES=JAC J7:2400
EXEMPT_USERNAMES=hussein,sasha_f
DB_PATH=/app/data/car_rental_bot.sqlite3
MEDIA_GROUP_WAIT_SECONDS=3
```

## 4. Запустить

```bash
docker compose up -d --build
```

Проверить логи:

```bash
docker compose logs -f autostaxbot
```

## 5. Назначить рабочий чат

Добавьте бота в рабочий чат и отправьте там `/set_work_chat` от пользователя с доступом к отчетам.

## 6. Обновление

После изменения кода:

```bash
docker compose up -d --build
```

База хранится в `./data/car_rental_bot.sqlite3`, поэтому при пересборке контейнера данные не пропадают.
