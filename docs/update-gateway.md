# Recovera update gateway cluster

Recovera gateways let appliances update from a private GitHub repository
without storing GitHub credentials on every appliance. The cluster is
active-active: each location independently caches, verifies, and serves the
same signed releases. There is no primary node, shared database, virtual IP,
or inter-gateway quorum.

The appliance tries the configured HTTPS origins in order on every check and
on every asset download. If a site, DNS record, or Internet connection is
unavailable, it continues with the next origin. A gateway continues serving
its last verified cached release during a GitHub outage.

## Security boundaries

- Each gateway holds a fine-grained GitHub token limited to read-only Contents
  access for the Recovera repository.
- Each gateway holds only *public* Recovera release and access-token keys.
- The release private keys never go on a gateway or an appliance.
- Appliance gateway credentials are independently signed, channel-scoped,
  expire within 366 days, and can be revoked by token identifier.
- A compromised gateway cannot create an accepted Recovera update because the
  appliance independently verifies the release manifest and all hashes.

## Deploy each gateway

Create a public DNS name for every location and forward TCP 80 and 443 to its
Ubuntu server. Caddy obtains and renews the TLS certificate, so the host must
be reachable for ACME validation. Create a fine-grained GitHub token with
read-only Contents permission for the one private repository and save it in a
root-readable temporary file.

From a Recovera checkout on each Ubuntu gateway:

```bash
sudo ./gateway/install.sh \
  --hostname updates-west.example.com \
  --github-token-file /root/recovera-github-read-token
sudo rm -f /root/recovera-github-read-token
curl -fsS https://updates-west.example.com/healthz
```

Repeat with `updates-east.example.com`, or as many independent locations as
needed. Use separate GitHub read tokens per gateway so one site can be revoked
without taking down the others.

## Issue an appliance credential

Run this only on a trusted administrative workstation that holds the gateway
access signing key. It does not require or expose the release signing key:

```bash
python3 gateway/recovera-gateway-token \
  --signing-key /secure/recovera-gateway-access-key \
  --subject customer-or-appliance-name \
  --channel stable --days 365 \
  --output customer-or-appliance-name.token
```

Copy the token to an appliance over a trusted channel, then configure all
gateway origins:

```bash
sudo install -o root -g root -m 0600 appliance.token /etc/recovera/gateway-token
sudo sed -i 's|^UPDATE_ORIGINS=.*|UPDATE_ORIGINS=https://updates-west.example.com,https://updates-east.example.com|' \
  /etc/recovera/upgrade.conf
sudo recovera-upgrade check
```

Do not put the access signing key in an OVA. Provision an issued appliance
token after deployment. To revoke a token, decode its middle base64url segment,
add its `jti` to `gateway/config/revocations.json` on every gateway, and restart
the gateway containers. Existing release-signature verification remains
unchanged.

## Vaultwarden and offline custody

Store the active release private key and the gateway access private key as
separate encrypted Vaultwarden attachments with restricted organization
access. Store the recovery release private key offline on two encrypted media
copies in separate physical locations. Record the public fingerprints in the
recovery procedure and test restoration without creating a release.

The recovery public key is shipped to appliances in advance. Using the offline
private key should require an incident/change record and two-person approval.
After a recovery signing event, rotate the active key through a bridge release.

## Operations

```bash
cd gateway
sudo docker compose ps
sudo docker compose logs --tail=100 gateway
sudo docker compose exec -T gateway /opt/recovera-gateway/recovera-gateway sync
sudo docker compose pull
sudo docker compose up -d --build
```

Monitor `/healthz` externally at every location. Also perform an authenticated
channel check; `/healthz` intentionally proves only that the process is alive.
Test failover quarterly by making the first configured hostname unreachable
and running `sudo recovera-upgrade check` on a non-production appliance.
