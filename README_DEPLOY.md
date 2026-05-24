# Деплой Telegram-бота на Koyeb

Эта инструкция рассчитана на запуск через GitHub и Koyeb Worker.

## 1. Загрузить проект в GitHub

1. Создайте новый репозиторий на GitHub.
2. Загрузите в него файлы проекта.
3. Проверьте, что файл `.env` не попал в GitHub. Он закрыт в `.gitignore`.

## 2. Создать сервис в Koyeb

1. Откройте Koyeb.
2. Нажмите Create Service.
3. Выберите GitHub repository.
4. Выберите репозиторий с ботом.
5. Тип сервиса выберите Worker.
6. Build type оставьте Python/Nixpacks или Automatic.

## 3. Указать команду запуска

В поле Run command укажите:

```bash
python main.py
```

В проекте также есть `Procfile`:

```text
worker: python main.py
```

## 4. Добавить Environment Variables

В настройках сервиса Koyeb откройте Environment variables и добавьте:

```text
BOT_TOKEN=ваш_токен_бота
WORK_CHAT_ID=
APPROVER_USERNAMES=sergey,stax_ru
ADMIN_USERNAMES=stax_ru
REPORT_USERNAMES=Fedos_AV,D_u_a
FREE_MODELS=JAC J7:10
DRIVER_RATES=JAC J7:2400
EXEMPT_USERNAMES=hussein,sasha_f
DB_PATH=/tmp/car_rental_bot.sqlite3
MEDIA_GROUP_WAIT_SECONDS=3
```

`BOT_TOKEN` вставляется только в Koyeb, не в GitHub.

Важно: `/tmp/car_rental_bot.sqlite3` подходит для первого запуска. Если нужно, чтобы история аренд гарантированно сохранялась между пересозданиями сервиса, подключите постоянное хранилище Koyeb Volume и укажите `DB_PATH` внутри него.

## 5. Запустить сервис

Нажмите Deploy. После запуска бот должен появиться в статусе Running.

## 6. Смотреть Logs

Откройте сервис в Koyeb и перейдите во вкладку Logs. Если токен указан неверно или отсутствует, в логах будет ошибка.

## 7. Перезапустить сервис

Откройте сервис в Koyeb и нажмите Redeploy или Restart.

## 8. После запуска

1. Отключите privacy mode у бота через BotFather.
2. Добавьте бота в рабочий чат.
3. В рабочем чате отправьте `/set_work_chat` от пользователя с правами.
4. В личном чате с ботом отправьте `/start`.
