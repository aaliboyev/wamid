import typer

from . import digest as digest_cmd
from . import init as init_cmd
from . import journal as journal_cmd
from . import log as log_cmd
from . import project as project_cmd
from . import record as record_cmd
from . import repo as repo_cmd
from . import serve as serve_cmd
from . import voice as voice_cmd

app = typer.Typer(help="wamid — personal-narrative CLI", no_args_is_help=True)
app.command("init")(init_cmd.init)
app.command("info")(init_cmd.info)
app.add_typer(project_cmd.app, name="project")
app.add_typer(repo_cmd.app, name="repo")
app.add_typer(voice_cmd.app, name="voice")
app.add_typer(journal_cmd.app, name="journal")
app.add_typer(record_cmd.app, name="record")
app.add_typer(digest_cmd.app, name="digest")
app.command("log")(log_cmd.log)
app.command("recent")(log_cmd.recent)
app.command("serve")(serve_cmd.serve)
