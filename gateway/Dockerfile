FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/recovera-gateway
COPY gateway/recovera-gateway gateway/recovera_gateway_auth.py gateway/recovera-gateway-token ./
COPY tools/verify-release.py ./verify-release.py
RUN chmod 0755 recovera-gateway recovera-gateway-token verify-release.py \
    && useradd --system --home /var/lib/recovera-gateway --shell /usr/sbin/nologin recovera-gateway \
    && install -d -o recovera-gateway -g recovera-gateway /var/lib/recovera-gateway

USER recovera-gateway
EXPOSE 8080
ENTRYPOINT ["/opt/recovera-gateway/recovera-gateway"]
CMD ["serve"]
