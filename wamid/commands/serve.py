import typer
from rich.console import Console

console = Console()


def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes"),
):
    """Run the optional HTTP API. Requires the [server] extra."""
    try:
        import uvicorn  # noqa: F401
        import wamid.api  # noqa: F401
    except ImportError:
        console.print(
            "[red]server extra not installed.[/red] install with:\n"
            "  [bold]uv sync --extra server[/bold]"
        )
        raise typer.Exit(1)
    import uvicorn
    uvicorn.run("wamid.api:app", host=host, port=port, reload=reload)
