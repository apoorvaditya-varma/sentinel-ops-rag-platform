"""`python -m src.web` - start the web app (binds to localhost by default)."""

import uvicorn

from src.config import get_settings
from src.logging_setup import setup_logging


def main() -> None:
    setup_logging()
    settings = get_settings()
    # access_log off: requests are logged by our middleware with request IDs instead.
    uvicorn.run("src.web.main:app", host=settings.web_host, port=settings.web_port,
                access_log=False, log_config=None)


if __name__ == "__main__":
    main()
