from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..services.journals import JournalNotFound, JournalService
from ..services.projects import ProjectService
from ..services.records import ProjectNotFound, RecordService
from ..services.session import open_session

app = typer.Typer(help="Inspect individual records (journal entries)", no_args_is_help=True)
console = Console()


def _bail(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


@app.command("show")
def show(record_id: int = typer.Argument(..., help="Record id")):
    """Show a single record: raw text, LLM summary, and metadata."""
    with open_session() as s:
        e = RecordService(s).get(record_id)
        if not e:
            _bail(f"record not found: {record_id}")
        project_slug = None
        if e.project_id:
            for p in ProjectService(s).list(include_archived=True):
                if p.id == e.project_id:
                    project_slug = p.slug
                    break
        try:
            j = JournalService(s).get(e.journal_id)
            journal_slug = j.slug
        except JournalNotFound:
            journal_slug = "(missing)"

    when = datetime.fromtimestamp(e.ts).isoformat()
    meta = (
        f"id: {e.id}\nwhen: {when}\nsource: {e.source}\n"
        f"journal: {journal_slug}\nproject: {project_slug or '(none)'}\n"
        f"external_id: {e.external_id or '(none)'}"
    )
    if e.source_meta:
        for k, v in e.source_meta.items():
            meta += f"\n{k}: {v}"

    console.print(Panel(meta, title=f"record #{e.id}", border_style="cyan"))
    console.print(Panel(e.text, title="raw", border_style="dim"))
    console.print(Panel(e.summary, title="summary (llm)", border_style="green"))


@app.command("list")
def list_(
    limit: int = typer.Option(20, "--limit", "-n"),
    project: str | None = typer.Option(None, "--project", "-p"),
    journal: str | None = typer.Option(None, "--journal", "-j"),
):
    """List recent records."""
    with open_session() as s:
        try:
            entries = RecordService(s).recent(limit=limit, project=project, journal=journal)
        except ProjectNotFound as e:
            _bail(f"project not found: {e.slug}")
        except JournalNotFound as e:
            _bail(str(e))
        project_names: dict[int, str] = {}
        journal_names: dict[int, str] = {}
        if entries:
            for p in ProjectService(s).list(include_archived=True):
                project_names[p.id] = p.slug
            for j in JournalService(s).list():
                journal_names[j.id] = j.slug

    if not entries:
        console.print("[dim]nothing logged yet.[/dim]")
        return

    t = Table(show_header=True, header_style="bold")
    t.add_column("id", justify="right")
    t.add_column("when")
    t.add_column("src")
    t.add_column("journal", style="dim")
    t.add_column("project", style="dim")
    t.add_column("summary", overflow="fold")
    for e in entries:
        when = datetime.fromtimestamp(e.ts).strftime("%Y-%m-%d %H:%M")
        proj = project_names.get(e.project_id, "") if e.project_id else ""
        j = journal_names.get(e.journal_id, "?")
        t.add_row(str(e.id), when, e.source, j, proj, e.summary)
    console.print(t)


@app.command("delete")
def delete(record_id: int = typer.Argument(...)):
    """Delete a record."""
    with open_session() as s:
        ok = RecordService(s).delete(record_id)
    if not ok:
        _bail(f"record not found: {record_id}")
    console.print(f"[green]deleted[/green] record {record_id}")
