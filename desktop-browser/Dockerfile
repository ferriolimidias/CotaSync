FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    DESKTOP_BROWSER_PROFILE_DIR=/data/profile

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    chromium \
    chromium-sandbox \
    curl \
    fonts-dejavu-core \
    fonts-liberation \
    novnc \
    openbox \
    procps \
    util-linux \
    websockify \
    x11-utils \
    x11vnc \
    xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash browser \
    && ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html

COPY desktop-browser/entrypoint.sh /usr/local/bin/desktop-browser-entrypoint
COPY desktop-browser/tcp_proxy.py /usr/local/bin/desktop-browser-tcp-proxy
COPY desktop-browser/policies.json /etc/chromium/policies/managed/cotasync.json
RUN chmod +x /usr/local/bin/desktop-browser-entrypoint

EXPOSE 6080 9222
VOLUME ["/data/profile"]

ENTRYPOINT ["/usr/local/bin/desktop-browser-entrypoint"]
