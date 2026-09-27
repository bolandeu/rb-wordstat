"""The `auth status [--check] --json` report (tools/docs/standard-release.md §8).

Its shape is a cross-tool contract — `tools-watch` reads it from every CLI
without knowing any provider — so it is pinned by `tests/test_auth.py`, and
changing it is a breaking change. Credential values never leave this
module: they are used only to scrub messages. Knows only `providers.Provider`:
how a provider talks to its service (HTTP or not) is the provider's business.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rich.markup import escape

from .. import output, providers
from ..core.errors import AuthRequired, CliError, CredentialsUnhealthy, InvalidArguments, ProviderError
from ..providers import Health, Provider
from . import manager

CHECK_TIMEOUT = 10.0  # seconds per provider (standard §8) — enforced by the provider's own client timeout
# Statuses that are a problem even for an optional provider: a credential is
# there but wrong. Anything else only counts against required providers.
ALWAYS_PROBLEMS = frozenset({"invalid", "expired"})
HEALTHY = frozenset({"ok", "unchecked"})


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z") if moment else None


def _scrub(message: str | None, secrets: list[str]) -> str | None:
    if message is None:
        return None
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message


def _run_check(provider_cls: type[Provider], target: str | None) -> Health:
    """`health_check()` with its exceptions mapped to statuses.

    No thread and no wall-clock timer here: a thread can't be killed, and
    the interpreter would still wait for it at exit. The 10 s limit is the
    provider's own request timeout (`HttpProvider.probe()` sets it; a
    non-HTTP provider passes `CHECK_TIMEOUT` to whatever it calls).
    """
    try:
        return provider_cls.for_health_check(target).health_check()
    except AuthRequired:
        return Health(status="invalid", message="the provider rejected the credential")
    except ProviderError as exc:
        if exc.status == 429:
            return Health(status="unreachable", message="rate limited (HTTP 429); retry later")
        return Health(status="unreachable", message=exc.message)
    except NotImplementedError as exc:
        return Health(status="unreachable", message=str(exc))
    except Exception as exc:
        return Health(status="unreachable", message=f"{type(exc).__name__}: {exc}")


def _entry(provider_cls: type[Provider], check: bool, target: str | None = None) -> dict:
    name = f"{provider_cls.name}:{target}" if target else provider_cls.name
    fields = list(provider_cls.credential_fields)
    legacy = provider_cls.legacy_env
    located = manager.locate_fields(name, fields, legacy_env=legacy)
    secrets = [value for value, _, _ in located.values()]
    # wordstat: доступы общие с serp — в source_ref и его места (SERP_*, serp:<provider>).
    env_refs = [
        manager.env_var_name(name, field)
        + f" (or {', '.join([*manager.shared_env_var_names(name, field), *([legacy[field]] if field in legacy else [])])})"
        for field in fields
    ]
    keychain_ref = "keychain service " + " or ".join(
        [manager.keychain_service(name), *manager.shared_keychain_services(name)]
    )
    missing = [field for field in fields if field not in located]
    sources = {source for _, source, _ in located.values()}

    entry: dict = {
        "provider": name,
        "required": provider_cls.required,
        "fields": fields,
        "source": "missing",
        "source_ref": f"{', '.join(env_refs)} or {keychain_ref}",
        "status": "missing",
        "expires_at": None,
        "quota": None,
        "message": None,
    }
    if missing:
        entry["message"] = f"not set: {', '.join(missing)}"
        return entry

    # Env vars override the keychain field by field; a mix is reported as env
    # (what wins) with every place named in source_ref (standard §8: no "mixed").
    used_env = [located[f][2] for f in fields if located[f][1] == "env"]
    used_keychain = sorted({located[f][2] for f in fields if located[f][1] == "keychain"})
    keychain_ref = f"keychain service {', '.join(used_keychain)}"
    if sources == {"keychain"}:
        entry.update(source="keychain", source_ref=keychain_ref)
    else:
        refs = ", ".join(used_env) + (f"; rest from {keychain_ref}" if "keychain" in sources else "")
        entry.update(source="env", source_ref=refs)

    if not check:
        entry["status"] = "unchecked"
        return entry
    health = _run_check(provider_cls, target)
    status = health.status
    if status == "ok" and health.expires_at and health.expires_at <= _now():
        status = "expired"
    entry.update(
        status=status,
        expires_at=_iso(health.expires_at),
        quota=vars(health.quota) if health.quota else None,
        message=_scrub(health.message, secrets),
    )
    return entry


def is_problem(entry: dict) -> bool:
    if entry["status"] in ALWAYS_PROBLEMS:
        return True
    return entry["required"] and entry["status"] not in HEALTHY


def _entries(provider_cls: type[Provider], check: bool, only: str | None) -> list[dict]:
    if not provider_cls.per_target:
        return [_entry(provider_cls, check)]
    # One entry per stored target ("<kind>:<target>"); none stored yet is
    # reported as the bare kind, `missing` — required or not, as declared.
    prefix = f"{provider_cls.name}:"
    if only is not None and only.startswith(prefix):
        targets = [only.removeprefix(prefix)]  # asked for by name: stored or env-only, it gets checked
    else:
        targets = [name.removeprefix(prefix) for name in manager.stored_names() if name.startswith(prefix)]
    if not targets:
        entry = _entry(provider_cls, check=False)
        entry["message"] = f"no {provider_cls.name} targets stored ('auth login --provider {prefix}<target>')"
        return [entry]
    return [_entry(provider_cls, check, target) for target in targets]


def select(known: list[type[Provider]], only: str | None) -> list[type[Provider]]:
    """Providers `only` refers to: a provider name, or `<kind>:<target>` of a per-target one."""
    if only is None:
        return known
    return [cls for cls in known if cls.name == only or (cls.per_target and only.startswith(f"{cls.name}:"))]


def report(tool: str, version: str, selected: list[type[Provider]], *, check: bool, only: str | None = None) -> dict:
    """The §8 report for `selected` providers (only those that declare credential fields)."""
    return {
        "tool": tool,
        "version": version,
        "checked_at": _iso(_now()),
        "credentials": [entry for cls in selected if cls.credential_fields for entry in _entries(cls, check, only)],
    }


def status(tool: str, version: str, *, check: bool, only: str | None) -> tuple[dict, CliError | None]:
    """What `auth status` emits: the report, and the problem (exit 3) if there is one."""
    known = providers.all_providers()
    selected = select(known, only)
    if only is not None and not selected:
        names = ", ".join(f"{cls.name}:<target>" if cls.per_target else cls.name for cls in known) or "none"
        raise InvalidArguments(f"Unknown provider '{only}' (known: {names}).")
    payload = report(tool, version, selected, check=check, only=only)
    problems = {entry["provider"]: entry["status"] for entry in payload["credentials"] if is_problem(entry)}
    return payload, CredentialsUnhealthy(problems) if problems else None


def render(payload: dict) -> None:
    """Human mode: one line per entry."""
    if not payload["credentials"]:
        output.human.echo("No providers with credentials.")
    for entry in payload["credentials"]:
        mark = {"ok": "[green]✓[/green]", "unchecked": "[dim]·[/dim]"}.get(entry["status"], "[red]✗[/red]")
        optional = "" if entry["required"] else " (optional)"
        detail = f" — {entry['message']}" if entry["message"] else ""
        expires = f", expires {entry['expires_at']}" if entry["expires_at"] else ""
        line = f"{entry['provider']}{optional}: {entry['status']} ({entry['source']}: {entry['source_ref']}){expires}{detail}"
        output.human.echo(f"{mark} {escape(line)}")
