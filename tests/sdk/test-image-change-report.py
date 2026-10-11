"""Image manifest source-report behavior."""

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location(
    "image_change_report", ROOT / "scripts/generate-image-change-report.py"
)
report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = report
spec.loader.exec_module(report)


def test_workflow_generates_reports_fail_open_and_passes_them_to_slack():
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/sync-debian-pre-release-mirror.yml").read_text()
    )
    steps = workflow["jobs"]["sync"]["steps"]
    generate = next(step for step in steps if "generate-image-change-report.py" in step.get("run", ""))
    notify = next(step for step in steps if "notify-mirror-versions.py" in step.get("run", ""))
    assert generate["continue-on-error"] is True
    assert "--evidence-dir out/daily-platform-images/change-reports" in generate["run"]
    assert "--replay-build" in generate["run"]
    assert "https://bitbucket.org/site/ssh" in generate["run"]
    assert "StrictHostKeyChecking=yes" in generate["run"]
    assert "--package-index" in generate["run"]
    assert generate["env"]["JENKINS_USER"] == (
        "${{ secrets.JENKINS_USERNAME || vars.JENKINS_USERNAME || "
        "secrets.JENKINS_USER || vars.JENKINS_USER }}"
    )
    assert "--image-change-report-dir" in notify["run"]
    assert "--replay-image-build" in notify["run"]
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["workflow_dispatch"]["inputs"]["replay_image_build"]["default"] == ""
    assert workflow["jobs"]["sync"]["env"]["REPLAY_IMAGE_BUILD"] == "${{ inputs.replay_image_build || '' }}"
    assert not (ROOT / "scripts/debian-package-source-map.json").exists()


def test_manifest_repository_url_drives_repository_identity_and_clone_transport():
    url = "https://bitbucket.org/sima-ai/cvu-sw.git"
    assert report.normalize_repository_url(url) == "https://bitbucket.org/sima-ai/cvu-sw"
    assert report.repository_name(url) == "sima-ai/cvu-sw"
    assert report.clone_url(url) == "ssh://git@bitbucket.org/sima-ai/cvu-sw.git"


def test_new_manifest_shape_parses_add_remove_and_modify():
    changes = report.parse_manifest_changes(
        "m linux-libc-dev 6.18.3-2031 -> 6.18.3-2032 https://bitbucket.org/sima-ai/simaai-linux.git\n"
        "+ troot-modalix 3.0.0~git.c7fee94 https://bitbucket.org/sima-ai/dvboot.git\n"
        "- atf-modalix 2.2.0~git.bdf0902 https://bitbucket.org/sima-ai/soc-simaai-atf.git\n"
    )
    assert len(changes) == 3
    assert changes[0].before_package == changes[0].after_package == "linux-libc-dev"
    assert changes[0].before_version == "6.18.3-2031"
    assert changes[0].after_version == "6.18.3-2032"
    assert changes[0].repository_url == "https://bitbucket.org/sima-ai/simaai-linux"
    assert changes[1].before_package is None
    assert changes[1].after_package == "troot-modalix"
    assert changes[2].before_package == "atf-modalix"
    assert changes[2].after_package is None


def test_legacy_manifest_shape_remains_readable_for_replays():
    changes = report.parse_manifest_changes(
        "> atf-modalix 2.2.0~git.bdf0902\n"
        "atf-modalix 2.2.0~git.bdf0902 <\n"
        "cvu-sw 2.2.0~git.80485fe | cvu-sw 2.2.0~git.8c62f50\n"
    )
    assert len(changes) == 3
    assert all(change.repository_url is None for change in changes)


def test_manifest_rejects_non_bitbucket_source_urls():
    try:
        report.parse_manifest_changes(
            "m package 1.0~git.abcdef0 -> 1.1~git.abcdef1 https://example.invalid/repo.git\n"
        )
    except ValueError as error:
        assert "Unsupported manifest repository URL" in str(error)
    else:
        raise AssertionError("Untrusted repository host was accepted")


def test_removed_package_is_described_in_report(tmp_path):
    change = report.parse_manifest_changes(
        "atf-modalix 2.2.0~git.bdf0902                         <\n"
    )[0]
    section = report.collect_section(
        change, tmp_path, object(), "modalix"
    )
    guidance = {
        "risk_level": "unknown",
        "risk_rationale": "Package removal requires review.",
        "affected_areas": [],
        "qa_focus": [],
        "consumer_guidance": [],
    }

    rendered = report.render_html("3.0.0_daily_develop_B1859", [section], "Summary", guidance)

    assert section["description"] == "This package was removed from the image."
    assert "Removed atf-modalix" in rendered
    assert "previously bdf0902" in rendered
    assert "This package was removed from the image." in rendered


def test_added_package_heading_is_plain_language():
    section = {
        "package": "troot-modalix",
        "before_package": None,
        "after_package": "troot-modalix",
        "before": None,
        "after": "3.0.0~git.c7fee94",
        "before_hash": None,
        "after_hash": "c7fee94766fbf89ae92ab262d45b19dd4921d4f0",
        "description": "This package was added to the image.",
        "repository": "sima-ai/dvboot",
        "repository_url": "https://bitbucket.org/sima-ai/dvboot",
        "source_path": None,
        "resolution_note": "",
        "comparison": {"commits": [], "files": [], "truncated": False},
    }
    guidance = {
        "risk_level": "unknown",
        "risk_rationale": "Review required.",
        "affected_areas": [],
        "qa_focus": [],
        "consumer_guidance": [],
    }

    rendered = report.render_html("build", [section], "Summary", guidance)

    assert "Added troot-modalix at" in rendered
    assert "c7fee94766fb" in rendered
    assert "not present → troot-modalix" not in rendered


def test_git_hash_accepts_legacy_and_timestamped_versions():
    assert report.git_hash("2.2.0~git.bdf0902") == "bdf0902"
    assert report.git_hash("3.0.0~git202609120138.aBcDeF0-1371") == "abcdef0"
    assert report.git_hash("1.4.1~git.c66e7682~git.0bf3ce8d4") == "0bf3ce8d4"


def test_package_index_recovers_parent_snapshot_times(tmp_path):
    packages = tmp_path / "Packages"
    packages.write_text(
        "Package: simaai-discovery\n"
        "Version: 3.0.0~git202610020121.1758321-1847\n\n"
        "Package: simaai-discovery\n"
        "Version: 3.0.0~git202610030121.5ae04ba-1855\n",
        encoding="utf-8",
    )
    index = report.PackageVersionIndex(packages)

    assert report.package_snapshot_time(
        index, "simaai-discovery", "3.0.0~git.1758321"
    ) == "2026-10-02T01:21:59Z"
    assert report.package_snapshot_time(
        index, "simaai-discovery", "3.0.0~git.5ae04ba"
    ) == "2026-10-03T01:21:59Z"


def test_new_repository_cache_fetches_remote_tracking_refs(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(report, "_FETCHED_REPOSITORIES", set())
    monkeypatch.setattr(
        report.subprocess,
        "run",
        lambda command, **_kwargs: (
            commands.append(command) or types.SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )
    monkeypatch.setattr(
        report,
        "run_git",
        lambda repository, *arguments, **_kwargs: commands.append((repository, *arguments)) or "",
    )
    repository = report.ensure_repository(
        tmp_path, "https://bitbucket.org/sima-ai/swsoc-elxr"
    )

    assert commands[0][:4] == ["git", "clone", "--bare", "--filter=blob:none"]
    assert commands[1] == (
        repository, "fetch", "--prune", "--no-tags", "origin",
        "+refs/heads/*:refs/remotes/origin/*",
    )


def test_snapshot_uses_refreshed_remote_first_parent(monkeypatch, tmp_path):
    calls = []
    commit = "a" * 40

    def resolve(_repository, revision):
        calls.append(("resolve", revision))
        return "b" * 40

    def run(_repository, *arguments, **_kwargs):
        calls.append(("git", *arguments))
        return commit

    monkeypatch.setattr(report, "resolve_commit", resolve)
    monkeypatch.setattr(report, "run_git", run)

    assert report.resolve_snapshot(tmp_path, "develop", "2026-10-03T01:21:59Z") == commit
    assert calls == [
        ("resolve", "refs/remotes/origin/develop"),
        ("git", "rev-list", "-1", "--first-parent", "--before=2026-10-03T01:21:59Z", "b" * 40),
    ]


def test_unresolvable_package_commits_fall_back_to_parent_snapshots(monkeypatch, tmp_path):
    packages = tmp_path / "Packages"
    packages.write_text(
        "Package: simaai-discovery\n"
        "Version: 3.0.0~git202610020121.1758321-1847\n\n"
        "Package: simaai-discovery\n"
        "Version: 3.0.0~git202610030121.5ae04ba-1855\n",
        encoding="utf-8",
    )
    snapshots = []
    comparisons = []
    monkeypatch.setattr(report, "ensure_repository", lambda *_args: tmp_path)
    monkeypatch.setattr(report, "resolve_commit_if_present", lambda *_args: None)

    def resolve_snapshot(_repository, timestamp):
        snapshots.append(timestamp)
        return "a" * 40

    def compare(_repository, before, after, web_url):
        comparisons.append((before, after, web_url))
        return {"relationship": "same", "commits": [], "files": [], "truncated": False}

    monkeypatch.setattr(report, "resolve_default_snapshot", resolve_snapshot)
    monkeypatch.setattr(report, "git_comparison", compare)
    section = report.collect_section(
        report.ManifestChange(
            "simaai-discovery", "3.0.0~git.1758321",
            "simaai-discovery", "3.0.0~git.5ae04ba",
            "https://bitbucket.org/sima-ai/swsoc-elxr",
        ),
        tmp_path,
        object(),
        "modalix",
        report.PackageVersionIndex(packages),
    )

    assert snapshots == [
        "2026-10-02T01:21:59Z",
        "2026-10-03T01:21:59Z",
    ]
    assert comparisons == [
        ("a" * 40, "a" * 40, "https://bitbucket.org/sima-ai/swsoc-elxr")
    ]
    assert section["comparison"]["relationship"] == "same"
    assert section["source_path"] is None
    assert section["provenance"] == "parent_repository_snapshot"
    assert "package build timestamp" in section["resolution_note"]


def test_each_manifest_row_carries_its_source_repository():
    changes = report.parse_manifest_changes(
        "m cvu-sw 2.2.0~git.80485fe -> 2.2.0~git.8c62f50 https://bitbucket.org/sima-ai/cvu-sw.git\n"
        "m linux-image-6.18.3-modalix 6.18.3-1833 -> 6.18.3-1847 https://bitbucket.org/sima-ai/simaai-linux.git\n"
        "+ u-boot-modalix-secure 2.2.0~git.365112fdb3 https://bitbucket.org/sima-ai/sima-ai-uboot.git\n"
    )
    assert [report.repository_name(change.repository_url) for change in changes] == [
        "sima-ai/cvu-sw", "sima-ai/simaai-linux", "sima-ai/sima-ai-uboot"
    ]


def test_direct_manifest_git_revisions_are_resolved(monkeypatch, tmp_path):
    change = report.ManifestChange(
        "cvu-sw", "2.2.0~git.abcdef0", "cvu-sw", "2.2.0~git.abcdef1",
        "https://bitbucket.org/sima-ai/cvu-sw",
    )
    revisions = []
    monkeypatch.setattr(report, "ensure_repository", lambda *_args: tmp_path)

    def resolve(_repository, revision):
        revisions.append(revision)
        return ("a" if revision == "abcdef0" else "b") * 40

    monkeypatch.setattr(report, "resolve_commit_if_present", resolve)
    monkeypatch.setattr(
        report,
        "git_comparison",
        lambda *_args: {"relationship": "same", "commits": [], "files": [], "truncated": False},
    )

    section = report.collect_section(
        change, tmp_path, object(), "modalix",
    )

    assert revisions == ["abcdef0", "abcdef1"]
    assert section["before_hash"] == "a" * 40
    assert section["after_hash"] == "b" * 40
    assert section["comparison"]["relationship"] == "same"


def test_jenkins_timeout_degrades_to_unavailable_provenance(tmp_path):
    class TimedOutJenkins:
        def source_commit(self, *_args):
            raise subprocess.TimeoutExpired("curl", 70)

    change = report.ManifestChange(
        "linux-image-6.18.3-modalix", "6.18.3-1833",
        "linux-image-6.18.3-modalix", "6.18.3-1847",
        "https://bitbucket.org/sima-ai/simaai-linux",
    )

    section = report.collect_section(
        change, tmp_path, TimedOutJenkins(), "modalix",
    )

    assert section["comparison"]["relationship"] == "unavailable"
    assert section["resolution_note"] == "Jenkins provenance could not be read: TimeoutExpired."


def test_replay_cli_reads_published_manifest_from_s3(monkeypatch, tmp_path):
    build = "3.0.0_daily_develop_B1855"
    s3 = object()
    generated = []
    monkeypatch.setitem(sys.modules, "mirror_aws", types.SimpleNamespace(s3_client=lambda: s3))
    monkeypatch.setattr(report, "read_s3_manifest", lambda client, name: (
        "> package 1.0~git.abcdef0\n" if (client, name) == (s3, build) else ""
    ))

    def generate(name, manifest, *_args):
        generated.append((name, manifest))
        return ()

    monkeypatch.setattr(report, "generate", generate)
    monkeypatch.setattr(sys, "argv", [
        "generate-image-change-report.py",
        "--replay-build", build,
        "--output-dir", str(tmp_path / "reports"),
        "--cache-root", str(tmp_path / "cache"),
    ])

    assert report.main() == 0
    assert generated == [(build, "> package 1.0~git.abcdef0\n")]


def test_codex_exec_allows_ephemeral_non_git_report_directory(monkeypatch, tmp_path):
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"packages": [{"key": "package-transition"}]}))
    work_dir = tmp_path / "codex"
    work_dir.mkdir()
    commands = []

    def run(command, **_kwargs):
        if command == ["codex", "exec", "--help"]:
            return types.SimpleNamespace(
                returncode=0,
                stdout="--output-schema --output-last-message",
                stderr="",
            )
        commands.append(command)
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(json.dumps({
            "slack_summary": "• Moderate risk: validate camera workflows.",
            "release_guidance": {
                "risk_level": "moderate",
                "risk_rationale": "Runtime camera behavior changed.",
                "affected_areas": ["Camera image processing"],
                "qa_focus": ["Validate color rendering under each illuminant."],
                "consumer_guidance": ["Camera users should watch for color regressions."],
            },
            "packages": [{"key": "package-transition", "description": "Description"}],
        }))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(report.subprocess, "run", run)

    result = report.codex_enrich(context, work_dir, 30)
    assert result["release_guidance"]["risk_level"] == "moderate"
    assert "--skip-git-repo-check" in commands[0]
    prompt = commands[0][-1]
    assert "specific, observable validation scenarios" in prompt
    assert "mark the relevant risk as unknown" in prompt
    assert "Start every bullet with a short bold label" in prompt


def test_codex_timeout_does_not_echo_untrusted_evidence(monkeypatch, tmp_path, capsys):
    context = tmp_path / "context.json"
    context.write_text(json.dumps({
        "packages": [{"key": "package-transition", "description": "SECRET-EVIDENCE"}]
    }))
    work_dir = tmp_path / "codex"
    work_dir.mkdir()

    def run(command, **_kwargs):
        if command == ["codex", "exec", "--help"]:
            return types.SimpleNamespace(
                returncode=0,
                stdout="--output-schema --output-last-message",
                stderr="",
            )
        raise subprocess.TimeoutExpired(command, 7)

    monkeypatch.setattr(report.subprocess, "run", run)

    assert report.codex_enrich(context, work_dir, 7) is None
    error = capsys.readouterr().err
    assert error == "Codex summary unavailable: timed out after 7 seconds\n"
    assert "SECRET-EVIDENCE" not in error


def test_release_guidance_is_rendered_and_escaped():
    guidance = {
        "risk_level": "high",
        "risk_rationale": "Potential <boot> impact",
        "affected_areas": ["Secure boot"],
        "qa_focus": ["Verify signed image boot"],
        "consumer_guidance": ["Stage rollout & monitor boot failures"],
    }
    sections = [{
        "package": "package",
        "before_package": "package",
        "after_package": "package",
        "before": "1",
        "after": "2",
        "before_hash": "a" * 40,
        "after_hash": "b" * 40,
        "description": "Changed.",
        "repository": "sima-ai/swsoc-elxr",
        "repository_url": "https://bitbucket.org/sima-ai/swsoc-elxr",
        "source_path": "configs/packages/<package>",
        "resolution_note": "",
        "comparison": {"commits": [], "files": [], "truncated": False},
    }]

    rendered = report.render_html(
        "build", sections,
        "• *Overall risk: high.* Check `bootctl` <output>.\n"
        "• *QA priority:* Verify signed image boot.",
        guidance,
    )

    assert "Release guidance" in rendered
    assert "Risk: high" in rendered
    assert "Potential &lt;boot&gt; impact" in rendered
    assert "Stage rollout &amp; monitor boot failures" in rendered
    assert '<ul class="overview-list">' in rendered
    assert '<strong class="overview-heading risk-high">Overall risk: high.</strong>' in rendered
    assert '<strong class="overview-heading">QA priority:</strong>' in rendered
    assert "<code>bootctl</code> &lt;output&gt;" in rendered
    assert "*Overall risk" not in rendered
    assert "configs/packages/&lt;package&gt;" in rendered


def test_html_omits_package_with_identical_resolved_commits():
    commit = "a" * 40
    section = {
        "package": "rebuild-only-package",
        "before_package": "rebuild-only-package",
        "after_package": "rebuild-only-package",
        "before": "1.0~git.old",
        "after": "1.0~git.new",
        "before_hash": commit,
        "after_hash": commit,
        "description": "Package metadata changed.",
        "repository": "sima-ai/repository",
        "repository_url": "https://bitbucket.org/sima-ai/repository",
        "source_path": "configs/packages/rebuild-only-package",
        "resolution_note": "",
        "comparison": {"commits": [], "files": [], "truncated": False},
    }
    guidance = {
        "risk_level": "low",
        "risk_rationale": "No source change.",
        "affected_areas": [],
        "qa_focus": [],
        "consumer_guidance": [],
    }

    rendered = report.render_html("build", [section], "Summary", guidance)

    assert "rebuild-only-package" not in rendered
