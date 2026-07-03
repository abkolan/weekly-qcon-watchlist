from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

from infoq_watchlist.models import Talk


SYNC_FIELD_SPECS = {
    "Status": ("SINGLE_SELECT", ["Backlog", "Queued", "Watching", "Watched", "Skipped", "Rewatch"]),
    "Year": ("NUMBER", []),
    "Decision": ("SINGLE_SELECT", ["watch", "skim", "transcript", "background", "skip"]),
    "Score": ("NUMBER", []),
    "Speaker": ("TEXT", []),
    "Conference": ("TEXT", []),
    "Presentation URL": ("TEXT", []),
}


class CommandRunner(Protocol):
    """Small protocol so tests can mock GitHub CLI calls."""

    def __call__(self, args: list[str], input_text: str | None = None) -> str:
        """Run a command and return stdout."""


@dataclass(frozen=True, slots=True)
class GitHubSyncSettings:
    """Config needed to sync eligible talks to GitHub."""

    repo: str
    project_owner: str
    project_title: str
    project_number: int
    eligible_decisions: tuple[str, ...]
    batch_limit: int
    sleep_seconds: float
    default_status: str


@dataclass(frozen=True, slots=True)
class GitHubIssuePayload:
    """Rendered GitHub issue data for one talk."""

    title: str
    body: str
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CreatedIssue:
    """GitHub issue identifiers returned after creation."""

    number: int
    url: str
    node_id: str | None


@dataclass(frozen=True, slots=True)
class ProjectItem:
    """GitHub Project item identifier returned after adding an issue."""

    item_id: str


def settings_from_config(raw: dict[str, object]) -> GitHubSyncSettings:
    """Normalize the GitHub section from watchlist.toml."""
    return GitHubSyncSettings(
        repo=str(raw["repo"]),
        project_owner=str(raw["project_owner"]),
        project_title=str(raw["project_title"]),
        project_number=int(raw.get("project_number") or 0),
        eligible_decisions=tuple(str(item) for item in raw["eligible_decisions"]),
        batch_limit=int(raw["batch_limit"]),
        sleep_seconds=float(raw["sleep_seconds"]),
        default_status=str(raw["default_status"]),
    )


def build_issue_payload(talk: Talk) -> GitHubIssuePayload:
    """Build a deterministic issue title, body, and label set for one talk."""
    year = str(talk.year) if talk.year is not None else "unknown-year"
    conference = talk.conference or "QCon"
    title = f"[{year}][{conference}] {talk.title}"
    labels = sorted(_labels_for_talk(talk))
    body = "\n".join(
        [
            f"- Presentation: {talk.presentation_url or talk.url}",
            f"- Speaker: {talk.speaker or 'Unknown'}",
            f"- Company: {talk.company or 'Unknown'}",
            f"- Year: {year}",
            f"- Conference: {conference}",
            f"- Score: {talk.score:g}",
            f"- Decision: {talk.decision}",
            f"- Duration: {talk.duration_minutes or 'Unknown'} minutes",
            "",
            f"Why: {talk.reason}",
            "",
            f"Tags: {', '.join(talk.tags) if talk.tags else 'none'}",
        ]
    )
    return GitHubIssuePayload(title=title, body=body, labels=tuple(labels))


def create_issue(
    settings: GitHubSyncSettings,
    payload: GitHubIssuePayload,
    runner: CommandRunner = None,
) -> CreatedIssue:
    """Create one GitHub issue through gh and return durable identifiers."""
    run = runner or run_gh
    ensure_labels(settings, payload.labels, run)
    created_url = run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            settings.repo,
            "--title",
            payload.title,
            "--body",
            payload.body,
            "--label",
            ",".join(payload.labels),
        ]
    ).strip()
    issue_json = run(
        [
            "gh",
            "issue",
            "view",
            created_url,
            "--repo",
            settings.repo,
            "--json",
            "number,url,id",
        ]
    )
    data = json.loads(issue_json)
    return CreatedIssue(number=int(data["number"]), url=str(data["url"]), node_id=data.get("id"))


def ensure_labels(settings: GitHubSyncSettings, labels: tuple[str, ...], runner: CommandRunner = None) -> None:
    """Create expected labels if they do not already exist."""
    run = runner or run_gh
    for label in labels:
        try:
            run(
                [
                    "gh",
                    "label",
                    "create",
                    label,
                    "--repo",
                    settings.repo,
                    "--color",
                    _label_color(label),
                    "--description",
                    "Managed by infoq-watchlist",
                ]
            )
        except RuntimeError as exc:
            if "already exists" not in str(exc).casefold():
                raise


def add_issue_to_project(
    settings: GitHubSyncSettings,
    issue: CreatedIssue,
    talk: Talk,
    runner: CommandRunner = None,
) -> ProjectItem:
    """Add an issue to the configured Project and set known fields."""
    run = runner or run_gh
    project_number = settings.project_number or resolve_project_number(settings, run)
    project_id = resolve_project_id(settings, project_number, run)
    fields = ensure_project_fields(settings, project_number, run)

    item_data = json.loads(
        run(
            [
                "gh",
                "project",
                "item-add",
                str(project_number),
                "--owner",
                settings.project_owner,
                "--url",
                issue.url,
                "--format",
                "json",
            ]
        )
    )
    item_id = str(item_data.get("id") or item_data.get("item", {}).get("id"))
    if not item_id:
        raise RuntimeError("GitHub Project item-add did not return an item id")

    _set_project_fields(settings, project_id, item_id, fields, talk, run)
    return ProjectItem(item_id=item_id)


def resolve_project_number(settings: GitHubSyncSettings, runner: CommandRunner = None) -> int:
    """Find a user/org Project number by title."""
    run = runner or run_gh
    data = json.loads(
        run(["gh", "project", "list", "--owner", settings.project_owner, "--format", "json", "--limit", "100"])
    )
    for project in data.get("projects", []):
        if project.get("title") == settings.project_title:
            return int(project["number"])
    raise RuntimeError(f"Project not found: {settings.project_title}")


def resolve_project_id(settings: GitHubSyncSettings, project_number: int, runner: CommandRunner = None) -> str:
    """Return the GraphQL project id for field edits."""
    run = runner or run_gh
    data = json.loads(
        run(["gh", "project", "view", str(project_number), "--owner", settings.project_owner, "--format", "json"])
    )
    project_id = data.get("id")
    if not project_id:
        raise RuntimeError("GitHub Project view did not return an id")
    return str(project_id)


def ensure_project_fields(
    settings: GitHubSyncSettings,
    project_number: int,
    runner: CommandRunner = None,
) -> dict[str, dict]:
    """Create missing Project fields and return field metadata by name."""
    run = runner or run_gh
    fields = _field_map(settings, project_number, run)
    for name, (data_type, options) in SYNC_FIELD_SPECS.items():
        if name in fields:
            continue
        args = [
            "gh",
            "project",
            "field-create",
            str(project_number),
            "--owner",
            settings.project_owner,
            "--name",
            name,
            "--data-type",
            data_type,
            "--format",
            "json",
        ]
        if options:
            args.extend(["--single-select-options", ",".join(options)])
        run(args)
    return _field_map(settings, project_number, run)


def run_gh(args: list[str], input_text: str | None = None) -> str:
    """Run gh and convert failures into clear RuntimeErrors."""
    completed = subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "gh command failed"
        raise RuntimeError(message)
    return completed.stdout


def _set_project_fields(
    settings: GitHubSyncSettings,
    project_id: str,
    item_id: str,
    fields: dict[str, dict],
    talk: Talk,
    runner: CommandRunner,
) -> None:
    """Set supported Project fields one command at a time."""
    values = {
        "Status": settings.default_status,
        "Year": talk.year,
        "Decision": talk.decision,
        "Score": talk.score,
        "Speaker": talk.speaker,
        "Conference": talk.conference,
        "Presentation URL": talk.presentation_url or talk.url,
    }
    for name, value in values.items():
        if value is None or name not in fields:
            continue
        field = fields[name]
        args = [
            "gh",
            "project",
            "item-edit",
            "--id",
            item_id,
            "--project-id",
            project_id,
            "--field-id",
            str(field["id"]),
        ]
        if field.get("type") == "ProjectV2SingleSelectField":
            option_id = _single_select_option_id(field, str(value))
            if not option_id:
                continue
            args.extend(["--single-select-option-id", option_id])
        elif name in {"Year", "Score"}:
            args.extend(["--number", str(value)])
        else:
            args.extend(["--text", str(value)])
        runner(args)


def _field_map(settings: GitHubSyncSettings, project_number: int, runner: CommandRunner) -> dict[str, dict]:
    """Read Project fields from gh output."""
    data = json.loads(
        runner(
            [
                "gh",
                "project",
                "field-list",
                str(project_number),
                "--owner",
                settings.project_owner,
                "--format",
                "json",
                "--limit",
                "100",
            ]
        )
    )
    fields: dict[str, dict] = {}
    for field in data.get("fields", []):
        # Normalize only our local lookup key so harmless UI whitespace does not
        # make the sync create duplicate Project fields.
        key = str(field["name"]).strip()
        fields.setdefault(key, field)
    return fields


def _single_select_option_id(field: dict, option_name: str) -> str | None:
    """Find a single-select option id by display name."""
    for option in field.get("options", []):
        if option.get("name") == option_name:
            return option.get("id")
    return None


def _labels_for_talk(talk: Talk) -> set[str]:
    """Build stable labels from score metadata."""
    labels = {"video", "qcon", f"decision/{talk.decision}"}
    if talk.year is not None:
        labels.add(f"year/{talk.year}")
    for tag in talk.tags:
        labels.add(f"topic/{_label_slug(tag)}")
    return labels


def _label_slug(value: str) -> str:
    """Normalize tags into compact GitHub label suffixes."""
    return value.strip().casefold().replace(" ", "-")


def _label_color(label: str) -> str:
    """Choose deterministic colors by label family."""
    if label.startswith("decision/"):
        return "0969da"
    if label.startswith("year/"):
        return "6f42c1"
    if label.startswith("topic/"):
        return "1f883d"
    return "57606a"


def sleep_between_writes(seconds: float) -> None:
    """Sleep between GitHub writes to avoid bursty sync behavior."""
    if seconds > 0:
        time.sleep(seconds)
