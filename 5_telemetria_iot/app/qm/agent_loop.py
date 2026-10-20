"""Local: corre el agente cada AGENT_INTERVAL segundos. En AWS lo dispara EventBridge."""
import logging
import time

import psycopg

from . import config
from .agent import run_once

log = logging.getLogger("agente")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log.info("modo %s, cada %d s", "llm" if config.ANTHROPIC_API_KEY else "reglas", config.AGENT_INTERVAL)
    while True:
        try:
            run_once()
        except psycopg.OperationalError as e:
            log.warning("base no disponible: %s", e)
        except Exception:
            log.exception("error en la corrida")
        time.sleep(config.AGENT_INTERVAL)


if __name__ == "__main__":
    main()
