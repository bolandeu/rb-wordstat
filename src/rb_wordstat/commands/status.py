from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services


@output.guard
def status(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Показать проект: имя, путь, очередь провайдеров."""
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    output.vecho(ctx, f"Resolved project root: {root}")
    config = services.load_config(root)
    output.emit_success(
        ctx,
        {"project": config.name, "path": str(root), "providers": config.providers},
        render_human=lambda data: output.human.key_values(
            "Status",
            {"project": data["project"], "path": data["path"], "providers": ", ".join(data["providers"])},
        ),
    )
