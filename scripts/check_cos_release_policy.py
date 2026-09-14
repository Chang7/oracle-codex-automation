#!/usr/bin/env python
"""Read-only Chat On Steroids release continuity checker.

This module detects the newest stable published GitHub Release and decides
whether it is eligible for *staging*. It never installs, promotes, restarts,
opens ChatGPT, creates a task, or treats elapsed silence as terminal evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT / "cos-release-policy.json"
POLICY_SCHEMA = "codex.web-gpt.cos-release-policy/v1"
REPORT_SCHEMA = "codex.web-gpt.cos-release-report/v1"
RELEASE_MODE = "latest-stable-published"
EXPECTED_REPOSITORY = "totec448-spec/chat-on-steroids"
PROMOTION_KEYS = {
    "watcher_read_only",
    "watcher_may_install",
    "watcher_may_restart",
    "require_customization_rebase",
    "require_exact_work_quiescent",
    "silence_is_terminal",
    "require_matching_extension",
    "require_chatgpt_refresh",
}
ROOT_KEYS = {
    "schema",
    "repository",
    "releases_api",
    "release_mode",
    "tag_prefix",
    "required_release_assets",
    "promotion",
}
_VERSION_RE = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")


class PolicyError(RuntimeError):
    pass


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise PolicyError(f"{label} keys must be exactly {sorted(expected)}; got {sorted(actual)}")


def parse_version(value: str, *, tag_prefix: str = "") -> tuple[int, int, int]:
    raw = str(value or "").strip()
    if tag_prefix and raw.startswith(tag_prefix):
        raw = raw[len(tag_prefix):]
    match = _VERSION_RE.fullmatch(raw)
    if match is None:
        raise PolicyError(f"invalid stable version: {value!r}")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


def _normalized_version(value: str, *, tag_prefix: str = "") -> str:
    return ".".join(str(part) for part in parse_version(value, tag_prefix=tag_prefix))


def validate_policy(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PolicyError("policy must be an object")
    _exact_keys(payload, ROOT_KEYS, "policy")
    if payload.get("schema") != POLICY_SCHEMA:
        raise PolicyError(f"policy schema must be {POLICY_SCHEMA}")
    if payload.get("repository") != EXPECTED_REPOSITORY:
        raise PolicyError(f"repository must be {EXPECTED_REPOSITORY}")
    if payload.get("release_mode") != RELEASE_MODE:
        raise PolicyError(f"release_mode must be {RELEASE_MODE}")
    if payload.get("tag_prefix") != "v":
        raise PolicyError("tag_prefix must be v")

    releases_api = str(payload.get("releases_api") or "")
    parsed = urlparse(releases_api)
    expected_path = f"/repos/{EXPECTED_REPOSITORY}/releases"
    if parsed.scheme != "https" or parsed.netloc != "api.github.com" or parsed.path != expected_path:
        raise PolicyError("releases_api must be the official GitHub releases endpoint for the configured repository")
    query = parse_qs(parsed.query)
    if query.get("per_page") != ["20"] or set(query) != {"per_page"}:
        raise PolicyError("releases_api must request exactly per_page=20")

    assets = payload.get("required_release_assets")
    if not isinstance(assets, list) or not assets or not all(isinstance(item, str) and item for item in assets):
        raise PolicyError("required_release_assets must be a non-empty string list")
    if len(set(assets)) != len(assets):
        raise PolicyError("required_release_assets must be unique")
    if assets != ["Chat-On-Steroids-Extension.zip"]:
        raise PolicyError("required_release_assets must require the matching companion extension archive")

    promotion = payload.get("promotion")
    if not isinstance(promotion, dict):
        raise PolicyError("promotion must be an object")
    _exact_keys(promotion, PROMOTION_KEYS, "promotion")
    if not all(isinstance(promotion[key], bool) for key in PROMOTION_KEYS):
        raise PolicyError("promotion values must be booleans")
    required_values = {
        "watcher_read_only": True,
        "watcher_may_install": False,
        "watcher_may_restart": False,
        "require_customization_rebase": True,
        "require_exact_work_quiescent": True,
        "silence_is_terminal": False,
        "require_matching_extension": True,
        "require_chatgpt_refresh": True,
    }
    for key, expected in required_values.items():
        if promotion[key] is not expected:
            raise PolicyError(f"promotion.{key} must be {str(expected).lower()}")
    return payload


def _release_assets(release: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = release.get("assets")
    if not isinstance(raw, list):
        return []
    assets: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        assets.append({
            "name": name,
            "state": item.get("state"),
            "digest": item.get("digest"),
        })
    return assets


def select_latest_stable(policy: Mapping[str, Any], releases: Any) -> dict[str, Any]:
    if not isinstance(releases, list):
        raise PolicyError("GitHub releases response must be a list")
    prefix = str(policy["tag_prefix"])
    candidates: list[tuple[tuple[int, int, int], Mapping[str, Any]]] = []
    for release in releases:
        if not isinstance(release, Mapping):
            continue
        if release.get("draft") is not False or release.get("prerelease") is not False:
            continue
        published_at = release.get("published_at")
        tag = release.get("tag_name")
        if not isinstance(published_at, str) or not published_at.strip() or not isinstance(tag, str):
            continue
        try:
            version = parse_version(tag, tag_prefix=prefix)
        except PolicyError:
            continue
        candidates.append((version, release))
    if not candidates:
        raise PolicyError("no stable published CoS release found")

    version, release = max(candidates, key=lambda item: item[0])
    assets = _release_assets(release)
    uploaded_names = {
        item["name"] for item in assets
        if item.get("state") in (None, "uploaded")
    }
    required = list(policy["required_release_assets"])
    missing = [name for name in required if name not in uploaded_names]
    return {
        "release_id": release.get("id"),
        "tag": str(release["tag_name"]),
        "version": ".".join(str(part) for part in version),
        "published_at": str(release["published_at"]),
        "html_url": release.get("html_url"),
        "assets": assets,
        "missing_release_assets": missing,
    }


def evaluate(
    policy: Mapping[str, Any],
    releases: Any,
    *,
    installed_version: str,
    customizations_verified: bool,
    active_exact_work: int,
    idle_seconds: int,
) -> dict[str, Any]:
    if active_exact_work < 0:
        raise PolicyError("active_exact_work must be non-negative")
    if idle_seconds < 0:
        raise PolicyError("idle_seconds must be non-negative")
    installed_tuple = parse_version(installed_version, tag_prefix=str(policy["tag_prefix"]))
    candidate = select_latest_stable(policy, releases)
    candidate_tuple = parse_version(candidate["version"])
    upgrade_available = candidate_tuple > installed_tuple
    missing = list(candidate["missing_release_assets"])

    result: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "repository": policy["repository"],
        "installed_version": ".".join(str(part) for part in installed_tuple),
        "candidate": candidate,
        "upgrade_available": upgrade_available,
        "missing_release_assets": missing,
        "active_exact_work": active_exact_work,
        "idle_seconds": idle_seconds,
        "customizations_verified": bool(customizations_verified),
        "time_alone_is_terminal": False,
        "replacement_authorized_by_silence": False,
        "live_install_authorized": False,
        "requires_extension_reload": upgrade_available,
        "requires_chatgpt_refresh": upgrade_available,
    }

    if not upgrade_available:
        result["decision"] = "NOOP_CURRENT_OR_NEWER"
    elif missing:
        result["decision"] = "HOLD_RELEASE_ASSETS_INCOMPLETE"
    elif active_exact_work:
        result["decision"] = "HOLD_ACTIVE_WORK"
    elif not customizations_verified:
        result["decision"] = "HOLD_CUSTOMIZATIONS_UNVERIFIED"
    else:
        result["decision"] = "READY_TO_STAGE_REBASE"
    return result


def fetch_releases(policy: Mapping[str, Any], *, timeout: float = 20.0) -> list[Any]:
    request = urllib.request.Request(
        str(policy["releases_api"]),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "oracle-codex-automation-cos-release-checker/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="strict"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PolicyError(f"failed to read CoS GitHub releases: {exc}") from exc
    if not isinstance(data, list):
        raise PolicyError("GitHub releases endpoint returned a non-list payload")
    return data


def _load_fixture(path: Path) -> list[Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"fixture could not be loaded: {path}") from exc
    if not isinstance(payload, dict) or set(payload) != {"releases"} or not isinstance(payload["releases"], list):
        raise PolicyError("fixture must be exactly an object containing a releases list")
    return payload["releases"]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Chat On Steroids stable-release continuity check")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--installed-version", required=True)
    parser.add_argument("--customizations-verified", action="store_true")
    parser.add_argument("--active-exact-work", type=int, default=0)
    parser.add_argument("--idle-seconds", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        policy = validate_policy(json.loads(args.policy.read_text(encoding="utf-8")))
        releases = _load_fixture(args.fixture) if args.fixture else fetch_releases(policy, timeout=args.timeout)
        report = evaluate(
            policy,
            releases,
            installed_version=args.installed_version,
            customizations_verified=args.customizations_verified,
            active_exact_work=args.active_exact_work,
            idle_seconds=args.idle_seconds,
        )
    except (OSError, json.JSONDecodeError, PolicyError) as exc:
        print(f"cos-release-policy: ERROR: {exc}", file=sys.stderr)
        return 2

    if args.output:
        _write_json(args.output, report)
    print(
        "cos-release-policy: "
        f"installed={report['installed_version']} "
        f"candidate={report['candidate']['version']} "
        f"decision={report['decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
