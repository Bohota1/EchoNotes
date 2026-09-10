"""Logging setup. Pipeline stages log with a stable stage name so a capture can be traced."""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)-28s %(message)s",
    )
