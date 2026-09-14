from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_cos_release_policy.py"
POLICY_PATH = ROOT / "cos-release-policy.json"


def load_module():
    assert MODULE_PATH.is_file(), "CoS release checker is not implemented"
    spec = importlib.util.spec_from_file_location("cos_release_policy_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def release(
    tag: str,
    *,
    draft: bool = False,
    prerelease: bool = False,
    published_at: str | None = "2026-09-14T20:10:12Z",
    assets: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": abs(hash(tag)) % 1_000_000 + 1,
        "tag_name": tag,
        "html_url": f"https://github.com/totec448-spec/chat-on-steroids/releases/tag/{tag}",
        "draft": draft,
        "prerelease": prerelease,
        "published_at": published_at,
        "assets": [
            {"name": name, "state": "uploaded", "digest": f"sha256:{'a' * 64}"}
            for name in (assets or ["Chat-On-Steroids-Extension.zip", "Chat-On-Steroids-Setup-x64.exe"])
        ],
    }


def checked_policy(module):
    return module.validate_policy(json.loads(POLICY_PATH.read_text(encoding="utf-8")))


def test_checked_in_policy_is_read_only_and_fail_closed() -> None:
    module = load_module()
    policy = checked_policy(module)
    assert policy["repository"] == "totec448-spec/chat-on-steroids"
    assert policy["release_mode"] == "latest-stable-published"
    assert policy["required_release_assets"] == ["Chat-On-Steroids-Extension.zip"]
    promotion = policy["promotion"]
    assert promotion["watcher_read_only"] is True
    assert promotion["watcher_may_install"] is False
    assert promotion["watcher_may_restart"] is False
    assert promotion["require_customization_rebase"] is True
    assert promotion["require_exact_work_quiescent"] is True
    assert promotion["silence_is_terminal"] is False
    assert promotion["require_matching_extension"] is True
    assert promotion["require_chatgpt_refresh"] is True


def test_latest_stable_ignores_draft_and_prerelease() -> None:
    module = load_module()
    policy = checked_policy(module)
    releases = [
        release("v2.1.13", draft=True),
        release("v2.2.0", prerelease=True),
        release("v2.1.12"),
        release("v2.0.9"),
    ]
    candidate = module.select_latest_stable(policy, releases)
    assert candidate["version"] == "2.1.12"
    assert candidate["tag"] == "v2.1.12"


def test_active_exact_work_blocks_staging_even_after_long_silence() -> None:
    module = load_module()
    result = module.evaluate(
        checked_policy(module),
        [release("v2.1.12")],
        installed_version="2.0.7",
        customizations_verified=True,
        active_exact_work=1,
        idle_seconds=86_400,
    )
    assert result["decision"] == "HOLD_ACTIVE_WORK"
    assert result["time_alone_is_terminal"] is False
    assert result["replacement_authorized_by_silence"] is False
    assert result["live_install_authorized"] is False


def test_upgrade_holds_until_customization_rebase_is_verified() -> None:
    module = load_module()
    result = module.evaluate(
        checked_policy(module),
        [release("v2.1.12")],
        installed_version="2.0.7",
        customizations_verified=False,
        active_exact_work=0,
        idle_seconds=0,
    )
    assert result["decision"] == "HOLD_CUSTOMIZATIONS_UNVERIFIED"
    assert result["upgrade_available"] is True


def test_verified_upgrade_is_stage_only_not_live_install() -> None:
    module = load_module()
    result = module.evaluate(
        checked_policy(module),
        [release("v2.1.12")],
        installed_version="2.0.7",
        customizations_verified=True,
        active_exact_work=0,
        idle_seconds=0,
    )
    assert result["decision"] == "READY_TO_STAGE_REBASE"
    assert result["candidate"]["version"] == "2.1.12"
    assert result["live_install_authorized"] is False
    assert result["requires_extension_reload"] is True
    assert result["requires_chatgpt_refresh"] is True


def test_missing_companion_extension_asset_fails_closed() -> None:
    module = load_module()
    result = module.evaluate(
        checked_policy(module),
        [release("v2.1.12", assets=["Chat-On-Steroids-Setup-x64.exe"])],
        installed_version="2.0.7",
        customizations_verified=True,
        active_exact_work=0,
        idle_seconds=0,
    )
    assert result["decision"] == "HOLD_RELEASE_ASSETS_INCOMPLETE"
    assert result["missing_release_assets"] == ["Chat-On-Steroids-Extension.zip"]


def test_current_or_newer_install_is_noop() -> None:
    module = load_module()
    result = module.evaluate(
        checked_policy(module),
        [release("v2.1.12")],
        installed_version="2.1.12",
        customizations_verified=True,
        active_exact_work=0,
        idle_seconds=0,
    )
    assert result["decision"] == "NOOP_CURRENT_OR_NEWER"
    assert result["upgrade_available"] is False


def test_fixture_cli_writes_machine_readable_stage_decision(tmp_path: Path) -> None:
    module = load_module()
    fixture = tmp_path / "releases.json"
    fixture.write_text(json.dumps({"releases": [release("v2.1.12")]}), encoding="utf-8")
    output = tmp_path / "report.json"
    code = module.main([
        "--fixture", str(fixture),
        "--installed-version", "2.0.7",
        "--customizations-verified",
        "--active-exact-work", "0",
        "--output", str(output),
    ])
    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["decision"] == "READY_TO_STAGE_REBASE"
    assert report["live_install_authorized"] is False


def test_update_guard_documents_cos_release_and_live_install_boundary() -> None:
    skill = " ".join((ROOT / "skills" / "mcp-update-guard" / "SKILL.md").read_text(encoding="utf-8").split())
    policy_doc = " ".join((ROOT / "docs" / "UPSTREAM_RUNTIME_POLICY.md").read_text(encoding="utf-8").split())
    assert "python scripts/check_cos_release_policy.py" in skill
    assert "latest stable published GitHub Release" in skill
    assert "silence alone never authorizes replacement or resubmission" in skill
    assert "READY_TO_STAGE_REBASE is staging authority only" in skill
    assert "reload the matching companion extension" in skill
    assert "refresh the affected ChatGPT tabs and connectors" in skill
    assert "Chat On Steroids release continuity" in policy_doc
    assert "unreleased `main`" in policy_doc
    assert "active or uncertain exact work blocks replacement" in policy_doc


def test_install_manifest_ships_cos_release_checker_and_policy() -> None:
    manifest = json.loads((ROOT / "install-manifest.json").read_text(encoding="utf-8"))
    includes = set(manifest["include"])
    assert "scripts/check_cos_release_policy.py" in includes
    assert "cos-release-policy.json" in includes
