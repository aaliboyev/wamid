from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table

from ..git import GitError
from ..services.journals import JournalNotFound, JournalService
from ..services.llm import LlmError, LlmService
from ..services.projects import ProjectNotFound, ProjectService
from ..services.records import (
    BadRepo,
    DuplicateExternal,
    RecordService,
)
from ..services.repos import RepoService
from ..services.session import open_session

console = Console()


def _bail(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def log(
    text: str | None = typer.Argument(None, help="Freeform entry. Omit to scan repos for new commits."),
    project: str | None = typer.Option(None, "--project", "-p", help="Project slug (filter for scan, attach for freeform)"),
    journal: str | None = typer.Option(None, "--journal", "-j", help="Journal to log into (default: 'default')"),
    raw: bool = typer.Option(False, "--raw", help="Skip LLM summarization (freeform only)"),
    since: str = typer.Option("24 hours ago", "--since"),
    until: str | None = typer.Option(None, "--until"),
    auto: bool = typer.Option(False, "--auto", help="No confirmation prompts"),
):
    """Log a freeform record, or scan tracked repos for new commits."""
    if text is not None:
        _log_freeform(text, project=project, journal=journal, raw=raw)
    else:
        _scan_commits(project=project, journal=journal, since=since, until=until, auto=auto)


def _log_freeform(text: str, project: str | None, journal: str | None, raw: bool):
    with open_session() as s:
        try:
            if raw:
                entry = RecordService(s).add(text=text, source="manual", project=project, journal=journal)
            else:
                llm = LlmService(s.cfg)
                try:
                    entry = RecordService(s).log(text=text, llm=llm, project=project, journal=journal)
                finally:
                    llm.close()
        except ProjectNotFound as e:
            _bail(f"project not found: {e.slug}")
        except JournalNotFound as e:
            _bail(str(e))
        except LlmError as e:
            _bail(str(e))
    console.print(f"[green]logged[/green] record {entry.id}")
    if entry.summary != entry.text:
        console.print(f"[dim]{entry.summary}[/dim]")


def _scan_commits(project: str | None, journal: str | None, since: str, until: str | None, auto: bool):
    with open_session() as s:
        rsvc = RecordService(s)
        try:
            JournalService(s).resolve(journal)  # validate journal exists
        except JournalNotFound as e:
            _bail(str(e))

        # Empty-repo guard: scan would silently return nothing otherwise.
        try:
            repos = RepoService(s).list(project=project)
        except ProjectNotFound as e:
            _bail(str(e))
        if not repos:
            hint = f" with --project {project}" if project else ""
            _bail(f"no repos tracked{hint}. add one with [bold]wamid repo add <path>[/bold]")

        try:
            items = list(rsvc.scan_commits(since=since, until=until, project=project))
        except ProjectNotFound as e:
            _bail(str(e))

        # Surface unreadable repos (no commits yet, missing dir, etc) without dying.
        bad = [b for b in items if isinstance(b, BadRepo)]
        for b in bad:
            console.print(f"[yellow]![/yellow] {b.repo.name}: {b.error}")

        candidates = [c for c in items if not isinstance(c, BadRepo)]
        new = [c for c in candidates if not c.already_logged]
        skipped = len(candidates) - len(new)
        if not new:
            msg = f"no new commits in [{since}]"
            if skipped:
                msg += f" ([dim]{skipped} already logged[/dim])"
            console.print(msg)
            return

        console.print(
            f"found [bold]{len(new)}[/bold] new commit(s)"
            + (f", skipping [dim]{skipped}[/dim] already logged" if skipped else "")
        )
        llm = LlmService(s.cfg)
        try:
            logged = 0
            for cand in new:
                c = cand.commit
                if auto:
                    try:
                        entry = rsvc.log_commit(llm, c, cand.repo, journal=journal)
                    except DuplicateExternal:
                        continue
                    except LlmError as e:
                        console.print(f"[red]✗[/red] {cand.repo.name}/{c.short_sha} — {e}")
                        continue
                    # Per-commit ✓ line so cron / git-hook logs are scannable.
                    console.print(
                        f"[green]✓[/green] {cand.repo.name}/{c.short_sha} "
                        f"[dim]→[/dim] {entry.summary}"
                    )
                    logged += 1
                    continue

                proj = f"[dim]→ {cand.repo.project_slug}[/dim]" if cand.repo.project_slug else ""
                console.print(
                    f"\n[bold]{cand.repo.name}[/bold] {c.short_sha} "
                    f"[dim]{datetime.fromtimestamp(c.ts):%Y-%m-%d %H:%M}[/dim] {proj}"
                )
                console.print(f"  {c.subject}")
                if not typer.confirm("log this?", default=True):
                    continue
                try:
                    entry = rsvc.log_commit(llm, c, cand.repo, journal=journal)
                except DuplicateExternal:
                    continue
                except LlmError as e:
                    console.print(f"[red]llm failed:[/red] {e} — skipping")
                    continue
                console.print(f"  [dim]→ {entry.summary}[/dim]")
                logged += 1
        finally:
            llm.close()
        console.print(f"\n[green]logged[/green] {logged}/{len(new)}")


def recent(
    limit: int = typer.Option(10, "--limit", "-n"),
    project: str | None = typer.Option(None, "--project", "-p"),
    journal: str | None = typer.Option(None, "--journal", "-j"),
):
    """Show recent records."""
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
    t.add_column("when")
    t.add_column("src")
    t.add_column("journal", style="dim")
    t.add_column("project", style="dim")
    t.add_column("summary", overflow="fold")
    for e in entries:
        when = datetime.fromtimestamp(e.ts).strftime("%Y-%m-%d %H:%M")
        proj = project_names.get(e.project_id, "") if e.project_id else ""
        j = journal_names.get(e.journal_id, "?")
        t.add_row(when, e.source, j, proj, e.summary)
    console.print(t)
