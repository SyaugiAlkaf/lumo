# Lumo trust layer as a microservice.
#
# This slim image runs the REST API + the deterministic policy/guard layer
# (injection scan, per-tx cap, supplier allowlist, attestation gating) with the
# chain adapter in `mock` mode — no keys, safe to publish. Callers get the trust
# decision as a service and wire their own chain/signer.
#
# For REAL on-chain settlement, extend this image: install the `stellar` CLI,
# mount a keystore, and set LUMO_CHAIN_ADAPTER=soroban + the LUMO_*_SOURCE vars.
FROM python:3.12-slim AS runtime

WORKDIR /app
COPY pyproject.toml ./
COPY lumo ./lumo
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /data && chown app:app /data

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV LUMO_API_HOST=0.0.0.0 \
    LUMO_API_PORT=8788 \
    LUMO_CHAIN_ADAPTER=mock \
    LUMO_PROVIDER=mock \
    LUMO_DB=/data/lumo.db

USER app
VOLUME ["/data"]
EXPOSE 8788
ENTRYPOINT ["docker-entrypoint.sh"]
