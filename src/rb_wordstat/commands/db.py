"""The `db` command group: migrate, inspect and reset the tool's database."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

from .. import output
from ..core import db

app = output.group("Manage the tool's database (shared PostgreSQL or local SQLite).")


def register(root: typer.Typer) -> None:
    """Add the `db` group to the CLI's root (the database part, copier's include_db)."""
    root.add_typer(app, name="db")


def _state(engine) -> dict:
    state = db.schema_state(engine)
    return {
        "database": db.describe(engine),
        "current": state.current,
        "head": state.head,
        "up_to_date": state.up_to_date,
    }


@app.command("status")
@output.guard
def status(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Show which database is used and its schema revision against this CLI's.

    Example: {cli} db status --json
    """
    engine = db.open_db(check=False)
    try:
        data = _state(engine)
    finally:
        engine.dispose()
    output.emit_success(ctx, data, render_human=lambda d: output.human.key_values("Database", d))


@app.command("upgrade")
@output.guard
def upgrade(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    dry_run: bool = output.DryRunOption,
) -> None:
    """Apply pending schema migrations to the database.

    The shared PostgreSQL is never migrated implicitly: run this from the
    released version after an upgrade that brings migrations. Concurrent runs
    wait for each other. A local SQLite database is migrated on every open anyway.

    Example: {cli} db upgrade --dry-run
    """
    engine = db.open_db(check=False)
    try:
        before = _state(engine)
        if output.is_dry_run(ctx):
            output.emit_success(
                ctx,
                {**before, "dry_run": True},
                render_human=lambda d: output.human.echo(
                    "Dry run: up to date."
                    if d["up_to_date"]
                    else f"Dry run: would migrate {d['current']} → {d['head']}."
                ),
            )
            return
        db.upgrade(engine)
        after = _state(engine)
    finally:
        engine.dispose()
    output.emit_success(
        ctx,
        {**after, "previous": before["current"]},
        render_human=lambda d: output.human.echo(
            f"Up to date at {d['head']}." if d["previous"] == d["head"] else f"Migrated {d['previous']} → {d['head']}."
        ),
    )


@app.command("import-sqlite")
@output.guard
def import_sqlite(
    ctx: typer.Context,
    path: Path = typer.Argument(None, help="SQLite file to import (default: this tool's local database)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    dry_run: bool = output.DryRunOption,
) -> None:
    """Copy a local SQLite database into the configured database, once.

    For the move to the shared PostgreSQL: set the database URL, then run
    this. Every target table must be empty; all rows go in one transaction.

    Example: {cli} db import-sqlite --dry-run
    """
    source = path or db.sqlite_path()
    engine = db.open_db()
    try:
        counts = db.import_sqlite(source, engine, dry_run=output.is_dry_run(ctx))
    finally:
        engine.dispose()
    output.emit_success(
        ctx,
        {"source": str(source), "dry_run": output.is_dry_run(ctx), "rows": counts},
        render_human=lambda d: output.human.key_values(
            ("Would import" if d["dry_run"] else "Imported") + f" from {d['source']}", d["rows"]
        ),
    )


@app.command("push")
@output.guard
def push(
    ctx: typer.Context,
    table: list[str] = typer.Option(None, "--table", help="Only this push table (repeatable; default: all of them)."),
    since: datetime = typer.Option(None, "--since", help="Only rows created at or after this date/time."),
    where: str = typer.Option(None, "--where", help='Extra SQL condition on the local table, e.g. "region = 213".'),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    dry_run: bool = output.DryRunOption,
) -> None:
    """Send new rows of the push tables from the local SQLite to production.

    Production is the PostgreSQL in `<CLI>_PROD_DATABASE_URL`; its schema
    revision must match this CLI's. Rows go in
    without their ids; one whose natural key is already there is skipped.
    One transaction; --dry-run counts exactly and writes nothing.

    Example: {cli} db push --since 2026-10-01 --dry-run
    """
    target = db.prod_engine()
    source = db.sqlite_engine(db.sqlite_path())
    try:
        db.upgrade(source)
        report = db.push(source, target, tables=table, since=since, where=where, dry_run=output.is_dry_run(ctx))
    finally:
        source.dispose()
        target.dispose()
    output.emit_success(
        ctx,
        {"target": db.describe(target), "dry_run": output.is_dry_run(ctx), "tables": report},
        render_human=lambda d: output.human.key_values(
            ("Would push to " if d["dry_run"] else "Pushed to ") + d["target"],
            {name: f"{t['sent']} sent, {t['skipped']} skipped" for name, t in d["tables"].items()},
        ),
    )
