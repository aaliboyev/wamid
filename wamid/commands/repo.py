from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..services.repos import (
    ProjectNotFound,
    RepoConflict,
    RepoNotFound,
    RepoService,
)
from ..services.session import open_session

app = typer.Typer(help="Manage tracked git repos", no_args_is_help=True)
console = Console()


def _bail(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


@app.command("add")
def add(
    path: str = typer.Argument(..., help="Path to the repo (can be relative)"),
    project: str | None = typer.Option(None, "--project", "-p", help="Attach to a project slug"),
    journal: str | None = typer.Option(None, "--journal", "-j", help="Default journal for this repo's commits"),
    name: str | None = typer.Option(None, "--name", help="Display name (default: dir basename)"),
    author: str | None = typer.Option(None, "--author", help="Filter commits to this git author"),
):
    """Track a repo. Optionally attach it to a project / journal."""
    with open_session() as s:
        try:
            r = RepoService(s).add(path, name=name, project=project, git_author=author, journal=journal)
        except RepoConflict as e:
            _bail(str(e))
        except ProjectNotFound as e:
            _bail(str(e))
    proj = f" → {r.project_slug}" if r.project_slug else " [dim](orphan)[/dim]"
    console.print(f"[green]added[/green] {r.name}{proj}")


@app.command("list")
def list_(
    project: str | None = typer.Option(None, "--project", "-p"),
    orphans: bool = typer.Option(False, "--orphans", help="Only repos not attached to a project"),
):
    """List tracked repos."""
    with open_session() as s:
        try:
            repos = RepoService(s).list(project=project, orphans_only=orphans)
        except ProjectNotFound as e:
            _bail(str(e))
    if not repos:
        console.print("[dim]no repos tracked yet — try [bold]wamid repo add <path>[/bold][/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("id", justify="right")
    t.add_column("name")
    t.add_column("project", style="dim")
    t.add_column("journal", style="dim")
    t.add_column("author")
    t.add_column("path", overflow="fold")
    for r in repos:
        t.add_row(
            str(r.id),
            r.name,
            r.project_slug or "[dim](none)[/dim]",
            r.journal_slug or "[dim](inherit)[/dim]",
            r.git_author or "",
            r.path,
        )
    console.print(t)


@app.command("show")
def show(ref: str = typer.Argument(..., help="Repo id or path")):
    """Show full details of a repo."""
    with open_session() as s:
        try:
            r = RepoService(s).get(ref)
        except RepoNotFound as e:
            _bail(str(e))
    body = (
        f"path: {r.path}\n"
        f"name: {r.name}\n"
        f"project: {r.project_slug or '(none)'}\n"
        f"journal: {r.journal_slug or '(inherit)'}\n"
        f"author: {r.git_author or '(any)'}\n"
        f"created_at: {datetime.fromtimestamp(r.created_at).isoformat()}"
    )
    console.print(Panel(body, title=f"repo #{r.id}", border_style="cyan"))


@app.command("update")
def update(
    ref: str = typer.Argument(...),
    name: str | None = typer.Option(None, "--name"),
    author: str | None = typer.Option(None, "--author"),
    journal: str | None = typer.Option(None, "--journal", "-j", help="Set default journal (empty string clears)"),
):
    """Update name, author filter, and/or journal binding."""
    if name is None and author is None and journal is None:
        _bail("nothing to update — pass --name / --author / --journal")
    with open_session() as s:
        try:
            r = RepoService(s).update(ref, name=name, git_author=author, journal=journal)
        except RepoNotFound as e:
            _bail(str(e))
    console.print(f"[green]updated[/green] {r.name}")


@app.command("attach")
def attach(
    ref: str = typer.Argument(...),
    project: str = typer.Argument(...),
):
    """Attach a repo to a project."""
    with open_session() as s:
        try:
            r = RepoService(s).attach(ref, project)
        except (RepoNotFound, ProjectNotFound) as e:
            _bail(str(e))
    console.print(f"[green]attached[/green] {r.name} → {r.project_slug}")


@app.command("detach")
def detach(ref: str = typer.Argument(...)):
    """Detach a repo from its project (becomes an orphan)."""
    with open_session() as s:
        try:
            r = RepoService(s).detach(ref)
        except RepoNotFound as e:
            _bail(str(e))
    console.print(f"[green]detached[/green] {r.name}")


@app.command("delete")
def delete(
    ref: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Stop tracking a repo. Does not touch the working tree."""
    if not yes:
        if not typer.confirm(f"stop tracking repo {ref!r}?"):
            raise typer.Exit(0)
    with open_session() as s:
        try:
            ok = RepoService(s).delete(ref)
        except RepoNotFound as e:
            _bail(str(e))
    if ok:
        console.print(f"[green]deleted[/green] {ref}")
