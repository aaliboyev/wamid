from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import libsql_client

from .. import config as config_mod
from .. import db as db_mod


@dataclass
class Session:
    client: libsql_client.Client
    cfg: config_mod.Config


@contextmanager
def open_session() -> Iterator[Session]:
    cfg = config_mod.load()
    with db_mod.client(cfg) as c:
        yield Session(client=c, cfg=cfg)
