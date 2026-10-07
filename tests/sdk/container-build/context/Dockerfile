FROM debian:bookworm-slim

COPY buildx-smoke /usr/local/bin/buildx-smoke
COPY neat-artifacts/ /opt/neat/bin/

ENTRYPOINT ["/usr/local/bin/buildx-smoke"]
