# NEAT Insight In The SDK Container

The SDK image installs `neat-insight` into `/opt/neat-insight/venv` and starts it automatically under `supervisord` when the container starts.

By default, Insight listens on port `9900`.

## Useful Commands

Run these commands inside the SDK container:

```bash
insight-admin status
insight-admin logs
insight-admin restart
insight-admin stop
```

## Temporary Upgrade

To temporarily upgrade Insight inside an existing container:

```bash
insight-admin update main latest
insight-admin restart
```

This only affects the current container.

## Permanent Upgrade

To make an Insight upgrade permanent, rebuild the SDK image with the desired channel and version:

```bash
NEAT_INSIGHT_BRANCH=main NEAT_INSIGHT_VERSION=latest ./build.sh sdk 2.0.0
```
