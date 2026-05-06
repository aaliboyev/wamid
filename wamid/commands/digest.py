from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..services.digests import (
    DigestExists,
    DigestService,
    NoEntriesToDigest,
    ProjectNotFound,
)
from ..services.llm import LlmError, LlmService
from ..services.session import open_session

app = typer.Typer(help="Generate and view rolling digests", no_args_is_help=True)
console = Console()


def _bail(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _parse_date(s: str | None) -> int | None:
    if not s:
        return None
    try:
        d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        _bail(f"date must be YYYY-MM-DD ({e})")
    return int(d.timestamp())


@app.command("generate")
def generate(
    period: str = typer.Option("day", "--period", "-P", help="day | week | month"),
    date: str | None = typer.Option(None, "--date", help="A date inside the window (YYYY-MM-DD, UTC). Default: today."),
    project: str | None = typer.Option(None, "--project", "-p"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing digest"),
):
    """Roll up journal entries into a digest for the given window."""
    if period not in ("day", "week", "month"):
        _bail("--period must be day, week, or month")
    when_ts = _parse_date(date)
    with open_session() as s:
        llm = LlmService(s.cfg)
        try:
            d = DigestService(s).generate(llm, period, when_ts=when_ts, project=project, force=force)
        except NoEntriesToDigest as e:
            _bail(str(e))
        except DigestExists as e:
            _bail(f"{e} (use --force to overwrite)")
        except ProjectNotFound as e:
            _bail(str(e))
        except LlmError as e:
            _bail(str(e))
        finally:
            llm.close()
    _print_digest(d)


@app.command("list")
def list_(
    period: str | None = typer.Option(None, "--period", "-P"),
    project: str | None = typer.Option(None, "--project", "-p"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """List digests."""
    if period and period not in ("day", "week", "month"):
        _bail("--period must be day, week, or month")
    with open_session() as s:
        try:
            items = DigestService(s).list(period=period, project=project, limit=limit)
        except ProjectNotFound as e:
            _bail(str(e))
    if not items:
        console.print("[dim]no digests yet — try [bold]wamid digest generate[/bold][/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("id", justify="right")
    t.add_column("period")
    t.add_column("window")
    t.add_column("project", style="dim")
    t.add_column("preview", overflow="fold")
    for d in items:
        win_start = datetime.fromtimestamp(d.start_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        preview = d.text.replace("\n", " ")[:80] + ("…" if len(d.text) > 80 else "")
        t.add_row(
            str(d.id), d.period, win_start,
            d.project_slug or "[dim](all)[/dim]", preview,
        )
    console.print(t)


@app.command("show")
def show(digest_id: int = typer.Argument(...)):
    """Show a single digest."""
    with open_session() as s:
        d = DigestService(s).get(digest_id)
    if not d:
        _bail(f"not found: {digest_id}")
    _print_digest(d)


@app.command("delete")
def delete(digest_id: int = typer.Argument(...)):
    """Delete a digest."""
    with open_session() as s:
        ok = DigestService(s).delete(digest_id)
    if not ok:
        _bail(f"not found: {digest_id}")
    console.print(f"[green]deleted[/green] {digest_id}")


def _print_digest(d):
    win_start = datetime.fromtimestamp(d.start_ts, tz=timezone.utc).isoformat()
    win_end = datetime.fromtimestamp(d.end_ts, tz=timezone.utc).isoformat()
    title = (
        f"#{d.id} · {d.period} · {win_start} → {win_end}"
        + (f" · {d.project_slug}" if d.project_slug else "")
    )
    console.print(Panel(d.text, title=title, border_style="cyan"))
