from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..services.journals import JournalNotFound
from ..services.llm import LlmError, LlmService
from ..services.session import open_session
from ..services.voice import (
    DEFAULT_NAME,
    UnknownPurpose,
    VoiceConflict,
    VoiceNotFound,
    VoiceService,
)

app = typer.Typer(help="Manage voice templates (system prompts)", no_args_is_help=True)
console = Console()


def _bail(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _resolve_template(template: str | None, from_file: Path | None) -> str:
    if template and from_file:
        _bail("pass either --template or --from-file, not both")
    if from_file:
        return from_file.read_text().strip()
    if template:
        return template
    _bail("provide --template TEXT or --from-file PATH (or use --ask)")
    return ""  # unreachable


def _wrap_known(e: Exception) -> str:
    return f"{e} (known: {VoiceService.purposes()})"


@app.command("list")
def list_(
    purpose: str | None = typer.Option(None, "--purpose", "-p"),
    journal: str | None = typer.Option(None, "--journal", "-j", help="Filter to a specific journal scope"),
):
    """List voices. Without --journal: global voices. With --journal: that journal's voices."""
    with open_session() as s:
        try:
            voices = VoiceService(s).list(purpose=purpose, journal=journal)
        except UnknownPurpose as e:
            _bail(_wrap_known(e))
        except JournalNotFound as e:
            _bail(str(e))
    t = Table(show_header=True, header_style="bold")
    t.add_column("purpose")
    t.add_column("name")
    t.add_column("scope", style="dim")
    t.add_column("active")
    t.add_column("source")
    t.add_column("preview", overflow="fold")
    for v in voices:
        scope = v.journal_slug or "(global)"
        active = "[bold green]●[/bold green]" if v.active else ""
        source = "[dim]default[/dim]" if v.is_default else "custom"
        preview = v.template.replace("\n", " ")[:80] + ("…" if len(v.template) > 80 else "")
        t.add_row(v.purpose, v.name, scope, active, source, preview)
    console.print(t)


@app.command("show")
def show(
    purpose: str = typer.Argument(...),
    name: str | None = typer.Argument(None, help="Voice name (default: whichever is active in scope)"),
    journal: str | None = typer.Option(None, "--journal", "-j"),
):
    """Print a voice's template."""
    with open_session() as s:
        try:
            v = VoiceService(s).get(purpose, name, journal=journal)
        except UnknownPurpose as e:
            _bail(_wrap_known(e))
        except VoiceNotFound as e:
            _bail(str(e))
        except JournalNotFound as e:
            _bail(str(e))
    label = "default" if v.is_default else ("active" if v.active else "inactive")
    scope = v.journal_slug or "global"
    title = f"{v.purpose} / {v.name} ({label}, {scope})"
    console.print(Panel(v.template, title=title, border_style="cyan"))


@app.command("add")
def add(
    purpose: str = typer.Argument(...),
    name: str | None = typer.Argument(None, help="Voice name (omit with --ask)"),
    template: str | None = typer.Option(None, "--template", "-t"),
    from_file: Path | None = typer.Option(None, "--from-file", "-f"),
    journal: str | None = typer.Option(None, "--journal", "-j", help="Scope this voice to a journal"),
    ask: bool = typer.Option(False, "--ask", help="LLM interviews you to craft the template"),
):
    """Add a voice variant. First add for a (purpose, scope) auto-activates."""
    if ask:
        if template or from_file:
            _bail("--ask cannot be combined with --template / --from-file")
        _add_via_ask(purpose, journal)
        return
    if not name:
        _bail("name required (or use --ask)")
    body = _resolve_template(template, from_file)
    with open_session() as s:
        try:
            v = VoiceService(s).add(purpose, name, body, journal=journal)
        except UnknownPurpose as e:
            _bail(_wrap_known(e))
        except (VoiceConflict, JournalNotFound) as e:
            _bail(str(e))
    flag = " [dim](active)[/dim]" if v.active else ""
    scope = f" @ {v.journal_slug}" if v.journal_slug else ""
    console.print(f"[green]added[/green] {v.purpose}/{v.name}{scope}{flag}")


def _add_via_ask(purpose: str, journal: str | None):
    with open_session() as s:
        svc = VoiceService(s)
        try:
            svc.list(purpose, journal=journal)
        except UnknownPurpose as e:
            _bail(_wrap_known(e))
        except JournalNotFound as e:
            _bail(str(e))
        llm = LlmService(s.cfg)
        try:
            history: list[dict] = []
            answer: str | None = None
            while True:
                step = svc.craft_step(llm, history, purpose, journal=journal, answer=answer)
                history = step.history
                if step.done and step.result:
                    v = step.result
                    flag = " [dim](active)[/dim]" if v.active else ""
                    scope = f" @ {v.journal_slug}" if v.journal_slug else ""
                    console.print(f"[green]added[/green] {v.purpose}/{v.name}{scope}{flag}")
                    console.print(Panel(v.template, border_style="cyan"))
                    return
                console.print(f"[bold cyan]?[/bold cyan] {step.question}")
                answer = console.input("[bold]> [/bold]")
        except LlmError as e:
            _bail(str(e))
        finally:
            llm.close()


@app.command("update")
def update(
    purpose: str = typer.Argument(...),
    name: str = typer.Argument(...),
    template: str | None = typer.Option(None, "--template", "-t"),
    from_file: Path | None = typer.Option(None, "--from-file", "-f"),
    journal: str | None = typer.Option(None, "--journal", "-j"),
):
    """Replace the template of an existing voice."""
    body = _resolve_template(template, from_file)
    with open_session() as s:
        try:
            v = VoiceService(s).update(purpose, name, body, journal=journal)
        except UnknownPurpose as e:
            _bail(_wrap_known(e))
        except (VoiceConflict, VoiceNotFound, JournalNotFound) as e:
            _bail(str(e))
    scope = f" @ {v.journal_slug}" if v.journal_slug else ""
    console.print(f"[green]updated[/green] {v.purpose}/{v.name}{scope}")


@app.command("use")
def use(
    purpose: str = typer.Argument(...),
    name: str = typer.Argument(..., help=f"Voice name, or '{DEFAULT_NAME}' to fall back"),
    journal: str | None = typer.Option(None, "--journal", "-j"),
):
    """Mark this voice active for its (purpose, scope)."""
    with open_session() as s:
        try:
            v = VoiceService(s).use(purpose, name, journal=journal)
        except UnknownPurpose as e:
            _bail(_wrap_known(e))
        except (VoiceNotFound, JournalNotFound) as e:
            _bail(str(e))
    scope = f" @ {v.journal_slug}" if v.journal_slug else ""
    console.print(f"[green]using[/green] {v.purpose}/{v.name}{scope}")


@app.command("delete")
def delete(
    purpose: str = typer.Argument(...),
    name: str = typer.Argument(...),
    journal: str | None = typer.Option(None, "--journal", "-j"),
):
    """Delete a voice variant. Cannot delete the built-in default."""
    with open_session() as s:
        try:
            removed = VoiceService(s).delete(purpose, name, journal=journal)
        except UnknownPurpose as e:
            _bail(_wrap_known(e))
        except (VoiceConflict, JournalNotFound) as e:
            _bail(str(e))
    if removed:
        scope = f" @ {journal}" if journal else ""
        console.print(f"[green]deleted[/green] {purpose}/{name}{scope}")
    else:
        _bail(f"voice not found: {purpose}/{name}")
