# sdk-triage

Use this skill when triaging GitHub issues in the `sima-neat/sdk` repository.

## Repository Scope

`sdk` packages the SiMa.ai Neat SDK as Docker images for supported host
architectures. It covers SDK image builds, image publishing, GHCR package
cleanup, SDK smoke tests, DevKit workspace helper behavior, SDK documentation,
and scripts/configuration that shape the container environment.

SDK issues may describe `sima-cli sdk setup` or `sima-cli sdk neat` behavior,
but first decide whether the failure is caused by this repository's image,
scripts, workflows, or documentation versus the `sima-cli` command
implementation.

## First Pass

Before classifying the issue, check whether it is likely a duplicate of an
existing issue from the provided issue context. Compare the title, command,
error text, image tag, branch/package name, host architecture, DevKit pairing
mode, and workflow name against existing discussion in the issue thread and any
available repo context.

If the issue appears to duplicate another issue, do not propose closing it and
do not use the `duplicate` label. Set `needs_human_review` to true, keep the
primary category aligned with the underlying problem, and mention in the public
comment that it may overlap with an existing report if the evidence is strong.
If the duplicate relationship is uncertain, ask for the missing detail needed to
confirm whether it is the same failure mode.

## Safety And Sensitivity

If the issue appears security-sensitive, customer-confidential, or likely to
contain private customer assets, set `needs_human_review` to true, keep the
public comment conservative, and do not request extended analysis.

Do not ask the reporter to upload credentials, tokens, private package URLs,
private registry credentials, proprietary logs, customer code, or full DevKit
images. Ask for redacted terminal output, public image/package references, host
OS/architecture, and reproducible command sequences instead.

If an issue likely requires private infrastructure, private package feeds,
private runner configuration, or release credentials, route it to human review.

## Classification

Use `bug` when the issue describes an SDK image build failure, broken published
image, missing tool/package in the container, smoke test failure, DevKit
workspace failure, GHCR cleanup regression, install/setup regression caused by
image contents, or documentation command that no longer works.

Use `enhancement` when the issue requests new SDK image content, host/platform
support, publishing behavior, setup flow, DevKit helper behavior, cleanup
policy, smoke coverage, or developer-experience improvement.

Use `documentation` when the issue is primarily about README/docs accuracy,
installation guidance, supported platform explanation, DevKit workflow
instructions, or confusing command examples.

Use `question` when the issue asks how SDK installation, image selection,
DevKit pairing, sysroot management, package publishing, or cleanup works and
does not yet identify a concrete defect or requested change.

Use `help wanted` only when the issue is suitable for external contribution and
does not require private package feeds, release credentials, private runners, or
internal infrastructure.

Do not propose `duplicate`, `invalid`, or `wontfix`. If an issue appears
duplicate, out of scope, or unsupported, set `needs_human_review` to true and
explain the evidence neutrally.

## Area Routing

Set `area` to one of these short names when the issue matches:

- `image-build`: Dockerfile/build script behavior, multi-arch image builds,
  host architecture selection, Buildx, sysroot package installation during
  build, or local `./build.sh` behavior.
- `image-publish`: GHCR image names/tags, multi-arch manifests, branch images,
  release images, staged/latest promotion, or package visibility.
- `package-cleanup`: GHCR branch package cleanup, deleted branch handling,
  protected release branches, canonical `sdk` tag cleanup, or cleanup dry-run
  behavior.
- `sdk-setup`: SDK setup behavior caused by image contents, container startup
  assumptions, workspace mount expectations, user/group setup inside the image,
  or Model Compiler extension availability from the SDK environment.
- `devkit-workspace`: DevKit pairing, NFS workspace, `dk` helper behavior,
  `devkit-syncd`, SSH access from the container, or `/workspace` mirroring.
- `container-runtime`: Docker/Colima runtime behavior that affects SDK
  containers, port mappings, privileged mode, `/dev` access, PID namespace,
  container naming, or stopped-container recovery.
- `sdk-networking`: SDK setup networking, DevKit connectivity, SDK-to-DevKit
  workspace/network configuration, port forwarding, NFS/rsync fallback, or
  network troubleshooting during SDK setup.
- `sysroot-toolchain`: `/opt/toolchain`, `simaai-init-build-env`, cross
  compiler/sysroot packages, `sysroot install/list/remove`, or target package
  availability.
- `docs`: README, `docs/`, installation instructions, DevKit workspace docs,
  building-software docs, or supported platform statements.
- `smoke-ci`: GitHub Actions, SDK smoke tests, Docker build workflow, runner
  architecture issues, or CI-only failures.
- `sdk-package`: SDK install package metadata, `sima-cli neat install
  sdk@...`, package resources, one-command SDK installation, or installer
  script behavior.
- `insight`: Insight installation or usage from inside the SDK image, Insight
  version baked into the SDK, or docs for Insight in SDK.
- `unknown`: not enough information to route.

## Common Missing Information

For SDK install/setup issues, ask for:

- host OS and architecture
- `sima-cli --version`
- exact command
- SDK image/package ref or tag
- complete redacted terminal output
- Docker or Colima status
- whether a DevKit was paired and the pairing mode, without requiring private IP
  disclosure if the reporter does not want to share it

For image build or CI issues, ask for:

- branch or commit
- architecture, such as `linux/amd64` or `linux/arm64`
- workflow/job name if CI-related
- full failing build step and error output
- whether the failure reproduces locally with `./build.sh`

For DevKit workspace issues, ask for:

- SDK image tag
- host OS and architecture
- DevKit software/platform version if available
- whether `dk shell` works
- redacted NFS/SSH/workspace error output

For SDK setup network issues, use the public sima-cli SDK networking
documentation as the first reference:

- https://developer.sima.ai/software/tools/sima-cli/sdk-networking/
- https://developer.sima.ai/software/tools/sima-cli/sdk-networking/troubleshooting

If the issue appears to match documented setup or troubleshooting guidance,
point the reporter to the relevant page and ask for the specific command output
that differs from the documented flow. Do not ask for private network details
unless the reporter can redact them.

For package cleanup or publishing issues, ask for:

- branch/tag name
- expected GHCR image or SDK install package name
- whether the branch is protected or deleted
- workflow run URL when available
- dry-run output when available

## Extended Analysis

Most issues should be triaged from the issue text, command output, and this
repo's local triage guidance. Do not request extended analysis just because the
issue mentions sima-cli, core, Model Compiler, or Insight.

Request extended analysis only when the issue includes enough specific detail
that checking another public repository can materially improve routing or the
next maintainer action.

Allowed cross-reference repositories:

- `sima-neat/sima-cli`
- `sima-neat/core`
- `sima-neat/model-compiler`
- `sima-neat/insight`

Request `sima-neat/sima-cli` when:

- the issue is primarily about `sima-cli sdk setup`, `sima-cli sdk neat`,
  `sima-cli neat install`, Docker permission recovery, SDK container selection,
  update prompts, or package installer orchestration.
- the report includes a concrete CLI command, CLI version, prompt sequence, or
  error message that can be checked against sima-cli behavior.

Request `sima-neat/core` when:

- the issue involves NEAT libraries, tutorials, Python bindings, installed core
  packages, runtime behavior, or SDK-contained artifacts that are produced by
  the core repo.
- the issue includes a core package version, tutorial path, NEAT API error, or
  runtime log that can be checked in core docs/tests/source.

Request `sima-neat/model-compiler` when:

- the issue involves Model Compiler extension installation, model compiler
  examples, BF16/INT8 behavior, compiled model archives, or compiler tools used
  inside the SDK.
- the issue includes compiler output, example path, extension package ref, or
  model archive details that can be checked against model-compiler docs or
  workflows.

Request `sima-neat/insight` when:

- the issue involves Insight installed in the SDK image, Insight launch/use from
  the SDK container, media/source workflows, or SDK docs that route to Insight.
- the issue includes Insight logs, package refs, workflow names, or docs paths
  that can be checked in the public Insight repository.

When extended analysis is useful, set:

- `extended_analysis_required`: `true`
- `extended_analysis_repos`: only the specific repo or repos needed from the
  allowlist above
- `extended_analysis_reason`: a concise explanation of what should be checked

If the issue lacks concrete logs, commands, image tags, package refs, workflow
names, or file paths, do not request extended analysis. Ask for the missing
information instead.

## Comment Style

Write a public triage comment with 2-4 short paragraphs:

- acknowledge the issue and state the likely area
- state whether it appears actionable, needs repro details, or needs human
  review
- mention specific evidence from the report
- ask only for missing information that would materially unblock investigation

Do not include a mechanical label list unless it is useful to the reporter. Do
not claim a root cause unless the issue text or checked public repository
context provides strong evidence.
