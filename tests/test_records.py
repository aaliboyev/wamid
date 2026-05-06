import pytest

from wamid.services.journals import JournalNotFound, JournalService
from wamid.services.projects import ProjectService
from wamid.services.records import (
    DuplicateExternal,
    ProjectNotFound,
    RecordService,
)


def test_add_manual_lands_in_default_journal(session):
    r = RecordService(session).add(text="hi")
    default = JournalService(session).get("default")
    assert r.journal_id == default.id
    assert r.source == "manual"
    assert r.summary == "hi"  # falls back to text


def test_add_with_project_resolves(session):
    ProjectService(session).add("X")
    r = RecordService(session).add(text="hi", project="x")
    assert r.project_id is not None


def test_add_with_unknown_project_raises(session):
    with pytest.raises(ProjectNotFound):
        RecordService(session).add(text="hi", project="nope")


def test_add_with_unknown_journal_raises(session):
    with pytest.raises(JournalNotFound):
        RecordService(session).add(text="hi", journal="nope")


def test_external_id_dedupes(session):
    svc = RecordService(session)
    svc.add(text="commit", source="commit", external_id="abc123")
    assert svc.has_external("abc123") is True
    with pytest.raises(DuplicateExternal):
        svc.add(text="commit again", source="commit", external_id="abc123")


def test_log_uses_llm(session, fake_llm):
    fake_llm.chat_response = lambda system, user: "[plain] " + user
    r = RecordService(session).log(text="commit msg", llm=fake_llm)
    assert r.summary == "[plain] commit msg"
    assert len(fake_llm.chat_calls) == 1


def test_log_uses_journal_scoped_voice_when_set(session, fake_llm):
    """The voice template_for(journal=...) returns the scoped template, and
    log() forwards the journal slug. Verifies the wiring, not the LLM output."""
    from wamid.services.journals import JournalService
    from wamid.services.voice import VoiceService

    JournalService(session).add("Eng")
    VoiceService(session).add("journal.summarize", "dry", "DRY VOICE", journal="eng")
    seen_systems = []
    fake_llm.chat_response = lambda system, user: seen_systems.append(system) or "ok"

    RecordService(session).log(text="x", llm=fake_llm, journal="eng")
    assert seen_systems == ["DRY VOICE"]


def test_recent_filters_by_project_and_journal(session):
    JournalService(session).add("Eng")
    ProjectService(session).add("Wamid")

    svc = RecordService(session)
    svc.add(text="default-no-project")
    svc.add(text="default-with-project", project="wamid")
    svc.add(text="eng-no-project", journal="eng")

    by_project = svc.recent(project="wamid")
    assert len(by_project) == 1
    assert by_project[0].text == "default-with-project"

    by_journal = svc.recent(journal="eng")
    assert len(by_journal) == 1
    assert by_journal[0].text == "eng-no-project"


def test_delete(session):
    svc = RecordService(session)
    r = svc.add(text="hi")
    assert svc.delete(r.id) is True
    assert svc.get(r.id) is None
    assert svc.delete(r.id) is False


def test_get_nonexistent(session):
    assert RecordService(session).get(9999) is None
