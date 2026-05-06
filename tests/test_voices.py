import pytest

from wamid.services.journals import JournalService
from wamid.services.voice import (
    DEFAULT_NAME,
    PURPOSES,
    UnknownPurpose,
    VoiceConflict,
    VoiceNotFound,
    VoiceService,
)


def test_template_for_default(session):
    template = VoiceService(session).template_for("journal.summarize")
    assert template == PURPOSES["journal.summarize"]


def test_unknown_purpose(session):
    with pytest.raises(UnknownPurpose):
        VoiceService(session).template_for("nope.purpose")


def test_first_global_add_auto_activates(session):
    v = VoiceService(session).add("journal.summarize", "dry", "Terse.")
    assert v.active is True


def test_second_global_add_inactive(session):
    svc = VoiceService(session)
    svc.add("journal.summarize", "dry", "Terse.")
    v = svc.add("journal.summarize", "warm", "Cozy.")
    assert v.active is False


def test_template_for_global_active_wins_over_default(session):
    svc = VoiceService(session)
    svc.add("journal.summarize", "dry", "DRY VOICE")
    assert svc.template_for("journal.summarize") == "DRY VOICE"


def test_journal_scoped_overrides_global(session):
    JournalService(session).add("Eng")
    svc = VoiceService(session)
    svc.add("journal.summarize", "dry", "GLOBAL DRY")
    svc.add("journal.summarize", "formal", "ENG FORMAL", journal="eng")
    # Engineering scope sees the scoped voice
    assert svc.template_for("journal.summarize", journal="eng") == "ENG FORMAL"
    # Other journals fall back to global
    assert svc.template_for("journal.summarize", journal="default") == "GLOBAL DRY"


def test_journal_scope_falls_back_to_global_then_default(session):
    JournalService(session).add("Eng")
    svc = VoiceService(session)
    # No scoped voice, no global voice → built-in default
    t = svc.template_for("journal.summarize", journal="eng")
    assert t == PURPOSES["journal.summarize"]


def test_use_switches_active(session):
    svc = VoiceService(session)
    svc.add("journal.summarize", "dry", "D")
    svc.add("journal.summarize", "warm", "W")
    svc.use("journal.summarize", "warm")
    assert svc.template_for("journal.summarize") == "W"


def test_use_default_clears_active(session):
    svc = VoiceService(session)
    svc.add("journal.summarize", "dry", "D")
    svc.use("journal.summarize", DEFAULT_NAME)
    # Falls back to built-in default
    assert svc.template_for("journal.summarize") == PURPOSES["journal.summarize"]


def test_reserved_default_name_cannot_be_added(session):
    with pytest.raises(VoiceConflict):
        VoiceService(session).add("journal.summarize", DEFAULT_NAME, "x")


def test_default_cannot_be_deleted(session):
    with pytest.raises(VoiceConflict):
        VoiceService(session).delete("journal.summarize", DEFAULT_NAME)


def test_default_cannot_be_updated(session):
    with pytest.raises(VoiceConflict):
        VoiceService(session).update("journal.summarize", DEFAULT_NAME, "x")


def test_update_not_found(session):
    with pytest.raises(VoiceNotFound):
        VoiceService(session).update("journal.summarize", "ghost", "x")


def test_delete_returns_true_when_removed(session):
    svc = VoiceService(session)
    svc.add("journal.summarize", "dry", "D")
    assert svc.delete("journal.summarize", "dry") is True
    assert svc.delete("journal.summarize", "dry") is False


def test_get_returns_default_when_no_active_custom(session):
    v = VoiceService(session).get("journal.summarize")
    assert v.is_default is True
    assert v.template == PURPOSES["journal.summarize"]


def test_get_named_voice(session):
    svc = VoiceService(session)
    svc.add("journal.summarize", "dry", "D")
    v = svc.get("journal.summarize", "dry")
    assert v.template == "D"
    assert v.is_default is False


def test_get_unknown_named_voice(session):
    with pytest.raises(VoiceNotFound):
        VoiceService(session).get("journal.summarize", "ghost")


def test_list_includes_synthetic_default(session):
    voices = VoiceService(session).list(purpose="journal.summarize")
    names = [v.name for v in voices]
    assert names == [DEFAULT_NAME]  # default-only baseline
    assert voices[0].active is True
