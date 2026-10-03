"""Package source map and image manifest report behavior."""

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parents[2]
MAP_PATH = ROOT / "scripts/debian-package-source-map.json"
spec = importlib.util.spec_from_file_location(
    "image_change_report", ROOT / "scripts/generate-image-change-report.py"
)
report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = report
spec.loader.exec_module(report)


def source_map():
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def expanded_sources(data):
    return [{**data["defaults"], **source} for source in data["sources"]]


def test_source_map_is_compact_runtime_configuration():
    data = source_map()
    assert data["schema_version"] == 2
    assert set(data) == {"schema_version", "services", "defaults", "sources"}
    assert data["defaults"] == {
        "source_ref": "develop",
        "version_provenance": "git_suffix",
    }
    serialized = MAP_PATH.read_text(encoding="utf-8")
    assert serialized.count("https://jenkins.eng.sima.ai") == 1
    assert "pre_release_build" not in serialized
    assert "sima-ai/" not in "\n".join(
        source.get("repository", "") for source in data["sources"]
    )
    forbidden = {"source_config", "jenkins_job", "note"}
    assert not any(forbidden.intersection(source) for source in data["sources"])


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


def test_defaults_expand_internal_and_external_repositories():
    data = source_map()
    sources = expanded_sources(data)
    cvu = next(source for source in sources if source.get("repository") == "cvu-sw")
    cartographer = next(source for source in sources if "cartographer" in source["package_regex"])
    assert report.repository_name(cvu, data["services"]) == "sima-ai/cvu-sw"
    assert report.source_url(cvu, data["services"]) == "ssh://git@bitbucket.org/sima-ai/cvu-sw.git"
    assert report.repository_name(cartographer, data["services"]) == "ros2/cartographer"
    assert report.source_url(cartographer, data["services"]) == "https://github.com/ros2/cartographer"


def test_latest_manifest_shape_parses_add_update_and_variant_switch():
    changes = report.parse_manifest_changes(
        "> atf-modalix 2.2.0~git.bdf0902\n"
        "cvu-sw 2.2.0~git.80485fe | cvu-sw 2.2.0~git.8c62f50\n"
        "troot-modalix 3.0.0~git.13cc855 | troot-modalix-secure 3.0.0~git.13cc855\n"
    )
    assert len(changes) == 3
    assert changes[0].before_package is None
    assert changes[1].before_package == changes[1].after_package == "cvu-sw"
    assert changes[2].before_package == "troot-modalix"
    assert changes[2].after_package == "troot-modalix-secure"


def test_git_hash_accepts_legacy_and_timestamped_versions():
    assert report.git_hash("2.2.0~git.bdf0902") == "bdf0902"
    assert report.git_hash("3.0.0~git202609120138.aBcDeF0-1371") == "abcdef0"


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


def test_parent_repository_package_uses_scoped_snapshots(monkeypatch, tmp_path):
    source = {
        "package_regex": "^simaai-discovery$",
        "repository": "swsoc-elxr",
        "source_ref": "develop",
        "source_path": "configs/packages/simaai-discovery",
        "version_provenance": "parent_repository_snapshot",
    }
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

    def resolve_snapshot(_repository, source_ref, timestamp):
        snapshots.append((source_ref, timestamp))
        return "a" * 40

    def compare(_repository, before, after, _web_url, source_path):
        comparisons.append((before, after, source_path))
        return {"relationship": "same", "commits": [], "files": [], "truncated": False}

    monkeypatch.setattr(report, "resolve_snapshot", resolve_snapshot)
    monkeypatch.setattr(report, "git_comparison", compare)
    section = report.collect_section(
        report.ManifestChange(
            "simaai-discovery", "3.0.0~git.1758321",
            "simaai-discovery", "3.0.0~git.5ae04ba",
        ),
        source,
        tmp_path,
        object(),
        "modalix",
        {"bitbucket": {
            "web_base_url": "https://bitbucket.org",
            "ssh_base_url": "ssh://git@bitbucket.org",
            "default_workspace": "sima-ai",
        }},
        report.PackageVersionIndex(packages),
    )

    assert snapshots == [
        ("develop", "2026-10-02T01:21:59Z"),
        ("develop", "2026-10-03T01:21:59Z"),
    ]
    assert comparisons == [("a" * 40, "a" * 40, source["source_path"])]
    assert section["comparison"]["relationship"] == "same"
    assert section["source_path"] == "configs/packages/simaai-discovery"
    assert "package build timestamp" in section["resolution_note"]


def test_every_package_rule_has_a_unique_mapping_for_known_manifest_packages():
    data = source_map()
    sources = expanded_sources(data)
    changes = report.parse_manifest_changes(
        "cvu-sw 2.2.0~git.80485fe | cvu-sw 2.2.0~git.8c62f50\n"
        "linux-image-6.18.3-modalix 6.18.3-1833 | linux-image-6.18.3-modalix 6.18.3-1847\n"
        "u-boot-modalix 2.2.0~git.365112fdb3 | u-boot-modalix-secure 2.2.0~git.365112fdb3\n"
    )
    mapped = [report.matching_source(change, sources) for change in changes]
    assert [item["repository"] for item in mapped] == [
        "cvu-sw", "simaai-linux", "sima-ai-uboot"
    ]
    assert mapped[0]["version_provenance"] == "git_suffix"
    assert mapped[1]["version_provenance"] == "jenkins_build_number"


def test_pinned_source_ref_is_used_when_package_version_has_no_git_hash(monkeypatch, tmp_path):
    source = {
        "package_regex": "^g2o$",
        "repository_url": "https://example.invalid/g2o",
        "source_ref": "debian/0_20230806-5",
        "version_provenance": "pinned_git",
    }
    change = report.ManifestChange("g2o", "0~20230806-4", "g2o", "0~20230806-5")
    resolved = "a" * 40
    revisions = []
    monkeypatch.setattr(report, "ensure_repository", lambda *_args: tmp_path)

    def resolve(_repository, revision):
        revisions.append(revision)
        return resolved

    monkeypatch.setattr(report, "resolve_commit", resolve)
    monkeypatch.setattr(
        report,
        "git_comparison",
        lambda *_args: {"relationship": "same", "commits": [], "files": [], "truncated": False},
    )

    section = report.collect_section(
        change, source, tmp_path, object(), "modalix",
        {"bitbucket": {"web_base_url": "https://bitbucket.org", "ssh_base_url": "ssh://git@bitbucket.org",
                       "default_workspace": "sima-ai"}},
    )

    assert revisions == [source["source_ref"], source["source_ref"]]
    assert section["before_hash"] == section["after_hash"] == resolved
    assert section["comparison"]["relationship"] == "same"


def test_jenkins_timeout_degrades_to_unavailable_provenance(tmp_path):
    class TimedOutJenkins:
        def source_commit(self, *_args):
            raise subprocess.TimeoutExpired("curl", 70)

    source = {
        "package_regex": "^linux-image-.*$",
        "repository": "simaai-linux",
        "version_provenance": "jenkins_build_number",
    }
    change = report.ManifestChange(
        "linux-image-6.18.3-modalix", "6.18.3-1833",
        "linux-image-6.18.3-modalix", "6.18.3-1847",
    )

    section = report.collect_section(
        change, source, tmp_path, TimedOutJenkins(), "modalix",
        {"bitbucket": {"web_base_url": "https://bitbucket.org", "ssh_base_url": "ssh://git@bitbucket.org",
                       "default_workspace": "sima-ai"}},
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
