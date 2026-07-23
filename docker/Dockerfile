FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    sqlite3 \
    curl \
    ca-certificates \
    pandoc \
    chromium \
    procps \
    imagemagick \
    file \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g openclaw@2026.4.23 \
    && chown -R node:node /usr/local/lib/node_modules/openclaw

COPY docker/pipeline-requirements.txt /tmp/pipeline-requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/pipeline-requirements.txt

COPY docker/build-context/ /home/openclaw/.openclaw-backlink/

RUN if [ -d /home/openclaw/.openclaw-backlink/assets ]; then \
      cp -a /home/openclaw/.openclaw-backlink/assets /home/openclaw/.openclaw-backlink-asset-seed; \
    else mkdir -p /home/openclaw/.openclaw-backlink-asset-seed; fi

COPY docker/entrypoint.sh /usr/local/bin/openclaw-backlink-entrypoint.sh
COPY docker/warm-plugins.sh /usr/local/bin/warm-plugins.sh
RUN chmod +x /usr/local/bin/openclaw-backlink-entrypoint.sh /usr/local/bin/warm-plugins.sh

RUN mkdir -p /home/openclaw/.config /home/openclaw/.openclaw-backlink/logs \
    && chown -R node:node /home/openclaw

ENV HOME=/home/openclaw \
    TZ=Asia/Kolkata \
    NODE_ENV=production \
    XDG_CONFIG_HOME=/home/openclaw/.config \
    OPENCLAW_STATE_DIR=/home/openclaw/.openclaw-backlink

RUN su node -s /bin/bash -c "HOME=/home/openclaw OPENCLAW_STATE_DIR=/home/openclaw/.openclaw-backlink XDG_CONFIG_HOME=/home/openclaw/.config /usr/local/bin/warm-plugins.sh"

USER node
WORKDIR /home/openclaw

ENTRYPOINT ["/usr/local/bin/openclaw-backlink-entrypoint.sh"]
