from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..services.llm import LlmError, LlmService
from ..services.projects import VALID_STATUS, VALID_VISIBILITY, ProjectService
from ..services.session import open_session

app = typer.Typer(help="Manage projects", no_args_is_help=True)
console = Console()


def _bail(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _parse_date(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        _bail(f"date must be YYYY-MM-DD: {s}")
        return None


def _parse_tags(s: str | None) -> list[str] | None:
    if s is None:
        return None
    return [t.strip() for t in s.split(",") if t.strip()]


@app.command("add")
def add(
    name: str | None = typer.Argument(None, help="Project name (omit with --ask)"),
    description: str | None = typer.Option(None, "--description", "-d"),
    slug: str | None = typer.Option(None, "--slug"),
    tagline: str | None = typer.Option(None, "--tagline"),
    homepage: str | None = typer.Option(None, "--homepage", help="Homepage URL"),
    repo: str | None = typer.Option(None, "--repo", help="Canonical repository URL"),
    started: str | None = typer.Option(None, "--started", help="YYYY-MM-DD"),
    ended: str | None = typer.Option(None, "--ended", help="YYYY-MM-DD"),
    tags: str | None = typer.Option(None, "--tags", help="Comma-separated"),
    featured: bool = typer.Option(False, "--featured"),
    visibility: str = typer.Option("public", "--visibility", "-v"),
    status: str = typer.Option("active", "--status"),
    color: str | None = typer.Option(None, "--color", help="Hex or name"),
    emoji: str | None = typer.Option(None, "--emoji"),
    ask: bool = typer.Option(False, "--ask", help="LLM interview"),
):
    """Add a new project."""
    if ask:
        _add_via_ask()
        return
    if not name:
        _bail("name required (or use --ask)")
    if visibility not in VALID_VISIBILITY:
        _bail(f"visibility must be one of {sorted(VALID_VISIBILITY)}")
    if status not in VALID_STATUS:
        _bail(f"status must be one of {sorted(VALID_STATUS)}")
    with open_session() as s:
        try:
            p = ProjectService(s).add(
                name=name, description=description, slug=slug,
                tagline=tagline, homepage_url=homepage, repo_url=repo,
                started_at=_parse_date(started), ended_at=_parse_date(ended),
                tags=_parse_tags(tags), featured=featured,
                visibility=visibility, status=status,
                color=color, emoji=emoji,
            )
        except ValueError as e:
            _bail(str(e))
    console.print(f"[green]added[/green] {p.slug} (id={p.id})")


def _add_via_ask():
    with open_session() as s:
        svc = ProjectService(s)
        llm = LlmService(s.cfg)
        try:
            history: list[dict] = []
            answer: str | None = None
            while True:
                step = svc.ask_step(llm, history, answer)
                history = step.history
                if step.done and step.result:
                    console.print(f"[green]created[/green] {step.result.slug} (id={step.result.id})")
                    return
                console.print(f"[bold cyan]?[/bold cyan] {step.question}")
                answer = console.input("[bold]> [/bold]")
        except LlmError as e:
            _bail(str(e))
        finally:
            llm.close()


@app.command("list")
def list_(
    all_: bool = typer.Option(False, "--all", "-a", help="Include archived"),
    visibility: str | None = typer.Option(None, "--visibility", "-v"),
):
    """List projects."""
    with open_session() as s:
        items = ProjectService(s).list(include_archived=all_, visibility=visibility)
    if not items:
        console.print("[dim]no projects yet[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("")  # emoji
    t.add_column("slug")
    t.add_column("name")
    t.add_column("status")
    t.add_column("vis", style="dim")
    t.add_column("★", justify="center")
    t.add_column("tagline", overflow="fold")
    for p in items:
        star = "★" if p.featured else ""
        t.add_row(
            p.emoji or "", p.slug, p.name, p.status,
            p.visibility, star, p.tagline or "",
        )
    console.print(t)


@app.command("show")
def show(slug: str = typer.Argument(...)):
    """Show full details of a project."""
    with open_session() as s:
        p = ProjectService(s).get(slug)
    if not p:
        _bail(f"not found: {slug}")
    fmt_ts = lambda t: datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat() if t else "—"
    lines = [
        f"name: {p.emoji + ' ' if p.emoji else ''}{p.name}",
        f"status: {p.status}    visibility: {p.visibility}    featured: {'yes' if p.featured else 'no'}",
    ]
    if p.tagline:
        lines.append(f"tagline: {p.tagline}")
    if p.homepage_url:
        lines.append(f"homepage: {p.homepage_url}")
    if p.repo_url:
        lines.append(f"repo: {p.repo_url}")
    if p.tags:
        lines.append(f"tags: {', '.join(p.tags)}")
    if p.primary_journal_slug:
        lines.append(f"primary journal: {p.primary_journal_slug}")
    if p.color:
        lines.append(f"color: {p.color}")
    lines.append(f"started: {fmt_ts(p.started_at)}    ended: {fmt_ts(p.ended_at)}")
    lines.append(f"created_at: {fmt_ts(p.created_at)}")
    if p.description:
        lines.append("")
        lines.append(p.description)
    console.print(Panel("\n".join(lines), title=p.slug, border_style="cyan"))


@app.command("update")
def update(
    slug: str = typer.Argument(...),
    name: str | None = typer.Option(None, "--name"),
    description: str | None = typer.Option(None, "--description", "-d"),
    tagline: str | None = typer.Option(None, "--tagline"),
    homepage: str | None = typer.Option(None, "--homepage"),
    repo: str | None = typer.Option(None, "--repo"),
    started: str | None = typer.Option(None, "--started"),
    ended: str | None = typer.Option(None, "--ended"),
    tags: str | None = typer.Option(None, "--tags"),
    featured: bool | None = typer.Option(None, "--featured/--no-featured"),
    visibility: str | None = typer.Option(None, "--visibility", "-v"),
    status: str | None = typer.Option(None, "--status"),
    color: str | None = typer.Option(None, "--color"),
    emoji: str | None = typer.Option(None, "--emoji"),
    journal: str | None = typer.Option(None, "--journal", "-j", help="Set primary journal (empty string clears)"),
):
    """Update fields on an existing project."""
    fields = {
        "name": name, "description": description, "tagline": tagline,
        "homepage_url": homepage, "repo_url": repo,
        "started_at": _parse_date(started), "ended_at": _parse_date(ended),
        "tags": _parse_tags(tags), "featured": featured,
        "visibility": visibility, "status": status,
        "color": color, "emoji": emoji,
        "primary_journal": journal,
    }
    if all(v is None for v in fields.values()):
        _bail("nothing to update — pass at least one flag")
    with open_session() as s:
        try:
            p = ProjectService(s).update(slug, **{k: v for k, v in fields.items() if v is not None})
        except ValueError as e:
            _bail(str(e))
    if not p:
        _bail(f"not found: {slug}")
    console.print(f"[green]updated[/green] {p.slug}")


@app.command("archive")
def archive(slug: str = typer.Argument(...)):
    """Soft-delete: mark project as archived."""
    with open_session() as s:
        ok = ProjectService(s).archive(slug)
    if not ok:
        _bail(f"not found: {slug}")
    console.print(f"[green]archived[/green] {slug}")


@app.command("delete")
def delete(
    slug: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Hard-delete the project. Records and repos become unattached."""
    if not yes:
        if not typer.confirm(f"delete project {slug!r}?"):
            raise typer.Exit(0)
    with open_session() as s:
        ok = ProjectService(s).delete(slug)
    if not ok:
        _bail(f"not found: {slug}")
    console.print(f"[green]deleted[/green] {slug}")
