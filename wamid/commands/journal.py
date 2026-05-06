from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..services.journals import (
    VALID_VISIBILITY,
    JournalConflict,
    JournalNotFound,
    JournalService,
)
from ..services.session import open_session

app = typer.Typer(help="Manage journals (record groupings)", no_args_is_help=True)
console = Console()


def _bail(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


@app.command("add")
def add(
    name: str = typer.Argument(...),
    description: str | None = typer.Option(None, "--description", "-d"),
    tagline: str | None = typer.Option(None, "--tagline"),
    visibility: str = typer.Option("public", "--visibility", "-v"),
    slug: str | None = typer.Option(None, "--slug"),
    color: str | None = typer.Option(None, "--color"),
    emoji: str | None = typer.Option(None, "--emoji"),
    featured: bool = typer.Option(False, "--featured"),
):
    """Add a new journal."""
    if visibility not in VALID_VISIBILITY:
        _bail(f"visibility must be one of {sorted(VALID_VISIBILITY)}")
    with open_session() as s:
        try:
            j = JournalService(s).add(
                name=name, description=description, tagline=tagline,
                visibility=visibility, slug=slug,
                color=color, emoji=emoji, featured=featured,
            )
        except (JournalConflict, ValueError) as e:
            _bail(str(e))
    console.print(f"[green]added[/green] {j.slug}")


@app.command("list")
def list_(visibility: str | None = typer.Option(None, "--visibility", "-v")):
    """List journals."""
    with open_session() as s:
        items = JournalService(s).list(visibility=visibility)
    t = Table(show_header=True, header_style="bold")
    t.add_column("")  # emoji
    t.add_column("slug")
    t.add_column("name")
    t.add_column("vis", style="dim")
    t.add_column("★", justify="center")
    t.add_column("tagline", overflow="fold")
    for j in items:
        star = "★" if j.featured else ""
        t.add_row(j.emoji or "", j.slug, j.name, j.visibility, star, j.tagline or "")
    console.print(t)


@app.command("show")
def show(slug: str = typer.Argument(...)):
    """Show full details of a journal."""
    with open_session() as s:
        try:
            j = JournalService(s).get(slug)
        except JournalNotFound as e:
            _bail(str(e))
    fmt_ts = lambda t: datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat() if t else "—"
    lines = [
        f"name: {j.emoji + ' ' if j.emoji else ''}{j.name}",
        f"visibility: {j.visibility}    featured: {'yes' if j.featured else 'no'}",
    ]
    if j.tagline:
        lines.append(f"tagline: {j.tagline}")
    if j.color:
        lines.append(f"color: {j.color}")
    lines.append(f"created_at: {fmt_ts(j.created_at)}")
    if j.description:
        lines.append("")
        lines.append(j.description)
    console.print(Panel("\n".join(lines), title=j.slug, border_style="cyan"))


@app.command("update")
def update(
    slug: str = typer.Argument(...),
    name: str | None = typer.Option(None, "--name"),
    description: str | None = typer.Option(None, "--description", "-d"),
    tagline: str | None = typer.Option(None, "--tagline"),
    visibility: str | None = typer.Option(None, "--visibility", "-v"),
    color: str | None = typer.Option(None, "--color"),
    emoji: str | None = typer.Option(None, "--emoji"),
    featured: bool | None = typer.Option(None, "--featured/--no-featured"),
):
    """Update fields on an existing journal."""
    fields = {
        "name": name, "description": description, "tagline": tagline,
        "visibility": visibility, "color": color, "emoji": emoji,
        "featured": featured,
    }
    if all(v is None for v in fields.values()):
        _bail("nothing to update — pass at least one flag")
    with open_session() as s:
        try:
            j = JournalService(s).update(slug, **{k: v for k, v in fields.items() if v is not None})
        except JournalNotFound as e:
            _bail(str(e))
        except ValueError as e:
            _bail(str(e))
    console.print(f"[green]updated[/green] {j.slug}")


@app.command("delete")
def delete(
    slug: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Delete a journal. Records and scoped voices are cascaded."""
    if not yes:
        if not typer.confirm(f"delete journal {slug!r}? all its records and scoped voices will go too."):
            raise typer.Exit(0)
    with open_session() as s:
        try:
            ok = JournalService(s).delete(slug)
        except JournalNotFound as e:
            _bail(str(e))
        except JournalConflict as e:
            _bail(str(e))
    if ok:
        console.print(f"[green]deleted[/green] {slug}")
