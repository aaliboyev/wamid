import pytest

from wamid.services.journals import (
    DEFAULT_SLUG,
    JournalConflict,
    JournalNotFound,
    JournalService,
)
from wamid.services.records import RecordService
from wamid.services.voice import VoiceService


def test_default_journal_seeded(session):
    j = JournalService(session).get(DEFAULT_SLUG)
    assert j.slug == DEFAULT_SLUG
    assert j.visibility == "public"


def test_resolve_falls_back_to_default(session):
    svc = JournalService(session)
    assert svc.resolve(None) == svc.get(DEFAULT_SLUG).id
    assert svc.resolve(DEFAULT_SLUG) == svc.get(DEFAULT_SLUG).id


def test_add_basic(session):
    j = JournalService(session).add("Engineering", description="builds")
    assert j.slug == "engineering"
    assert j.description == "builds"
    assert j.featured is False


def test_add_with_full_fields(session):
    j = JournalService(session).add(
        name="Engineering Log",
        description="public side",
        tagline="the work",
        visibility="public",
        slug="eng",
        color="#abc",
        emoji="🛠️",
        featured=True,
    )
    assert j.slug == "eng"
    assert j.tagline == "the work"
    assert j.emoji == "🛠️"
    assert j.featured is True


def test_add_duplicate_slug_raises(session):
    svc = JournalService(session)
    svc.add("X")
    with pytest.raises(JournalConflict):
        svc.add("X")


def test_add_invalid_visibility(session):
    with pytest.raises(ValueError):
        JournalService(session).add("X", visibility="hidden")


def test_list_orders_featured_first(session):
    svc = JournalService(session)
    svc.add("Plain")
    svc.add("Star", featured=True)
    items = svc.list()
    # default is created first by migration, then plain, then star (featured)
    assert items[0].slug == "star"  # featured DESC pins it to top


def test_list_filters_by_visibility(session):
    svc = JournalService(session)
    svc.add("Public", visibility="public")
    svc.add("Hidden", visibility="private")
    publics = svc.list(visibility="public")
    privates = svc.list(visibility="private")
    assert {j.slug for j in publics} == {"default", "public"}
    assert {j.slug for j in privates} == {"hidden"}


def test_update_partial(session):
    svc = JournalService(session)
    j = svc.add("X")
    updated = svc.update("x", tagline="new", featured=True)
    assert updated.tagline == "new"
    assert updated.featured is True
    # Untouched fields preserved
    assert updated.name == "X"


def test_update_invalid_visibility(session):
    svc = JournalService(session)
    svc.add("X")
    with pytest.raises(ValueError):
        svc.update("x", visibility="garbage")


def test_update_unknown_raises(session):
    with pytest.raises(JournalNotFound):
        JournalService(session).update("nope", name="x")


def test_delete_default_protected(session):
    with pytest.raises(JournalConflict):
        JournalService(session).delete(DEFAULT_SLUG)


def test_delete_cascades_records_and_voices(session):
    jsvc = JournalService(session)
    jsvc.add("X")
    # Add a record and a scoped voice in this journal
    RecordService(session).add(text="hi", journal="x")
    VoiceService(session).add("journal.summarize", "dry", "Be terse.", journal="x")

    assert RecordService(session).recent(journal="x"), "record exists"
    scoped = [v for v in VoiceService(session).list(journal="x") if not v.is_default]
    assert scoped, "voice exists"

    jsvc.delete("x")

    # Records gone
    with pytest.raises(JournalNotFound):
        RecordService(session).recent(journal="x")
    # Voices gone (they had journal_id pointing at the dead row)
    remaining_scoped = [
        v for v in VoiceService(session).list() if v.journal_slug == "x"
    ]
    assert remaining_scoped == []
