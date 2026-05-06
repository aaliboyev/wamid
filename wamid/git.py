"""Pure git plumbing: read commits from a working tree via subprocess.
No db, no LLM, no Session — only the dataclass and the read function."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    pass


@dataclass
class Commit:
    sha: str
    ts: int          # author/commit unix seconds
    author: str
    subject: str
    body: str

    @property
    def short_sha(self) -> str:
        return self.sha[:7]

    @property
    def text(self) -> str:
        """Subject + body for LLM consumption."""
        if self.body.strip():
            return f"{self.subject}\n\n{self.body}".strip()
        return self.subject


# ASCII separators avoid clashes with commit message content.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"
_FORMAT = _FIELD_SEP.join(["%H", "%ct", "%an", "%s", "%b"]) + _RECORD_SEP


def read_commits(
    path: str | Path,
    since: str | None = None,
    until: str | None = None,
    author: str | None = None,
) -> list[Commit]:
    """Run `git log` and parse the result. `since`/`until` are passed straight
    to git, so anything git understands works ('24 hours ago', '2026-05-01', etc).
    `author` filters by commit author (substring match)."""
    p = Path(path).expanduser().resolve()
    if not (p / ".git").exists() and not (p.parent / ".git").exists():
        # Not a strict check (worktrees, bare repos), but good enough for early exit.
        # Git will produce a clearer error if it actually isn't one.
        pass

    args = [
        "git", "-C", str(p), "log", "--no-merges",
        f"--pretty=format:{_FORMAT}",
    ]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    if author:
        args.append(f"--author={author}")

    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise GitError(f"git log failed in {p}: {e.stderr.strip() or e}") from e
    except FileNotFoundError as e:
        raise GitError("git not found on PATH") from e

    commits: list[Commit] = []
    for record in proc.stdout.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(_FIELD_SEP)
        if len(parts) < 5:
            continue
        sha, ts, an, subject, body = parts[0], parts[1], parts[2], parts[3], parts[4]
        try:
            ts_int = int(ts)
        except ValueError:
            continue
        commits.append(
            Commit(sha=sha, ts=ts_int, author=an, subject=subject.strip(), body=body.strip())
        )
    return commits
