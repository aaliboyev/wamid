import pytest

from wamid.services.projects import ProjectService
from wamid.services.records import RecordService
from wamid.services.repos import RepoService


def test_add_minimal(session):
    p = ProjectService(session).add("Wamid")
    assert p.slug == "wamid"
    assert p.status == "active"
    assert p.visibility == "public"
    assert p.featured is False
    assert p.tags == []


def test_add_full_fields(session):
    p = ProjectService(session).add(
        name="Wamid", description="cli", tagline="the work",
        homepage_url="https://x", repo_url="https://gh", started_at=1000,
        ended_at=2000, tags=["cli", "py"], featured=True,
        visibility="private", color="#abc", emoji="📓", status="shipped",
    )
    assert p.tagline == "the work"
    assert p.tags == ["cli", "py"]
    assert p.featured is True
    assert p.visibility == "private"
    assert p.status == "shipped"


def test_add_invalid_visibility(session):
    with pytest.raises(ValueError):
        ProjectService(session).add("X", visibility="hidden")


def test_add_invalid_status(session):
    with pytest.raises(ValueError):
        ProjectService(session).add("X", status="ongoing")


def test_slug_generation(session):
    p = ProjectService(session).add("Hello World!")
    assert p.slug == "hello-world"


def test_explicit_slug_wins(session):
    p = ProjectService(session).add("Hello World", slug="hi")
    assert p.slug == "hi"


def test_list_orders_featured_first(session):
    svc = ProjectService(session)
    svc.add("Plain")
    svc.add("Star", featured=True)
    items = svc.list()
    assert items[0].slug == "star"


def test_list_excludes_archived_by_default(session):
    svc = ProjectService(session)
    svc.add("A")
    svc.add("B")
    svc.archive("a")
    slugs = {p.slug for p in svc.list()}
    assert slugs == {"b"}
    slugs_all = {p.slug for p in svc.list(include_archived=True)}
    assert slugs_all == {"a", "b"}


def test_list_visibility_filter(session):
    svc = ProjectService(session)
    svc.add("Pub", visibility="public")
    svc.add("Priv", visibility="private")
    assert {p.slug for p in svc.list(visibility="public")} == {"pub"}
    assert {p.slug for p in svc.list(visibility="private")} == {"priv"}


def test_update_partial_preserves_others(session):
    svc = ProjectService(session)
    svc.add("X", description="old", tagline="t")
    updated = svc.update("x", description="new")
    assert updated.description == "new"
    assert updated.tagline == "t"


def test_update_tags_serializes_round_trip(session):
    svc = ProjectService(session)
    svc.add("X")
    updated = svc.update("x", tags=["a", "b", "c"])
    assert updated.tags == ["a", "b", "c"]


def test_update_invalid_status(session):
    svc = ProjectService(session)
    svc.add("X")
    with pytest.raises(ValueError):
        svc.update("x", status="bogus")


def test_archive_changes_status(session):
    svc = ProjectService(session)
    svc.add("X")
    assert svc.archive("x") is True
    assert svc.get("x").status == "archived"


def test_delete_sets_record_and_repo_project_to_null(session):
    psvc = ProjectService(session)
    psvc.add("X")
    RecordService(session).add(text="r", project="x")
    RepoService(session).add(path="/tmp", project="x")

    assert psvc.delete("x") is True

    rec = RecordService(session).recent()[0]
    assert rec.project_id is None

    rep = RepoService(session).list()[0]
    assert rep.project_id is None
    assert rep.project_slug is None


def test_delete_unknown_returns_false(session):
    assert ProjectService(session).delete("nope") is False
