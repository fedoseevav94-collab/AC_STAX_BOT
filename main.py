from bot.main import main

import asyncio
import logging
import time
import signal
import sys


def shutdown_handler(signum, frame):
    print("Получен сигнал остановки")
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            break
        except SystemExit:
            break
        except Exception:
            logging.exception("Бот упал, перезапуск через 5 секунд")
            time.sleep(5)
