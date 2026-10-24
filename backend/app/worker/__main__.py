from app import observability
from app.worker.runner import Worker

observability.configure_logging()

worker = Worker()
worker.handle_signals()
worker.run()
