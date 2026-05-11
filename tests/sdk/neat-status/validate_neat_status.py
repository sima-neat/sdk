#!/usr/bin/env python3
import json
import sys


def add_error(errors, message):
    errors.append(message)


def validate_status(data):
    errors = []

    if data.get("schema") != "sima.neat.status.v1":
        add_error(errors, f"Unexpected schema: {data.get('schema')}")

    environment = data.get("environment") or {}
    if environment.get("mode") != "elxr-sdk":
        add_error(errors, f"Unexpected environment mode: {environment.get('mode')}")
    if not environment.get("sdkVersion"):
        add_error(errors, "Missing environment.sdkVersion")
    if not environment.get("sysroot"):
        add_error(errors, "Missing environment.sysroot")

    components = data.get("components") or {}
    required_components = {
        "core",
        "gstPlugins",
        "insight",
        "modelSdkExtension",
        "pyneat",
        "runtime",
    }
    for name in sorted(required_components):
        component = components.get(name)
        if component is None:
            add_error(errors, f"Missing component: {name}")
            continue
        if not component.get("name"):
            add_error(errors, f"Missing components.{name}.name")

    for name in ["core", "gstPlugins", "insight", "pyneat", "runtime"]:
        component = components.get(name) or {}
        if not component.get("version"):
            add_error(errors, f"Missing components.{name}.version")

    insight = components.get("insight") or {}
    if not insight.get("version"):
        add_error(errors, "Missing components.insight.version")
    if not insight.get("tag"):
        add_error(errors, "Missing components.insight.tag")
    if not insight.get("venv"):
        add_error(errors, "Missing components.insight.venv")
    if insight.get("serviceState") not in {"Running", "Starting", "Unknown"}:
        add_error(
            errors,
            f"Unexpected components.insight.serviceState: {insight.get('serviceState')}",
        )

    model_sdk = components.get("modelSdkExtension") or {}
    if "installed" not in model_sdk:
        add_error(errors, "Missing components.modelSdkExtension.installed")
    if "version" not in model_sdk:
        add_error(errors, "Missing components.modelSdkExtension.version")
    elif model_sdk.get("installed") and not model_sdk.get("version"):
        add_error(errors, "Model SDK Extension is installed but version is empty")

    update_status = data.get("updateCheck", {}).get("status")
    if update_status not in {"ok", "skipped", "error", None}:
        add_error(errors, f"Unexpected updateCheck.status: {update_status}")

    return errors


def main():
    if len(sys.argv) != 2:
        print("Usage: validate_neat_status.py <neat-status.json>", file=sys.stderr)
        return 2

    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    errors = validate_status(data)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("Neat status validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
