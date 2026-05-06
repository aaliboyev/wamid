from typing import Iterator

from fastapi import Depends

from ..services.llm import LlmService
from ..services.session import Session, open_session


def session_dep() -> Iterator[Session]:
    with open_session() as s:
        yield s


def llm_dep(s: Session = Depends(session_dep)) -> Iterator[LlmService]:
    llm = LlmService(s.cfg)
    try:
        yield llm
    finally:
        llm.close()
