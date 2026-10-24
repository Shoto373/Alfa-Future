import logging

from app.worker.runner import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

worker = Worker()
worker.handle_signals()
worker.run()
