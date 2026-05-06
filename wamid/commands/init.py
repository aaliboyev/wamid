from rich.console import Console

from .. import config, db

console = Console()


def init():
    """Create config + db, run migrations."""
    path = config.write_default_config()
    console.print(f"config: {path}")
    cfg = config.load()
    with db.client(cfg) as c:
        ran = db.migrate(c)
    console.print(f"migrations applied: {ran}" if ran else "db up to date")


def info():
    """Show resolved config."""
    console.print(config.load().model_dump())
