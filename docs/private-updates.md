# Private updates without a hosted gateway

GitHub does not permit anonymous downloads from a private repository. Without
an Internet-facing Recovera gateway, an appliance must either hold a GitHub
read credential or receive signed update files manually. Neither method needs
an interactive `gh auth login` on the appliance.

## Option 1: root-only read token

Create a fine-grained GitHub personal access token with an expiration date,
access only to the Recovera repository, and read-only **Contents** permission.
Use a different token per appliance or recipient when practical so access can
be revoked without interrupting every installation. Never embed a shared token
in an OVA or installer payload.

Install it once from the appliance console or SSH session:

```bash
read -rsp 'Recovera GitHub read token: ' RECOVERA_TOKEN; echo
printf '%s\n' "$RECOVERA_TOKEN" | sudo tee /etc/recovera/github-token >/dev/null
sudo chown root:root /etc/recovera/github-token
sudo chmod 0600 /etc/recovera/github-token
unset RECOVERA_TOKEN
sudo recovera-upgrade check
```

The updater reads this file directly and uses GitHub's API for the private
channel and release assets. Users do not authorize the GitHub CLI. Remove the
file or revoke the token to remove that appliance's update access.

This is the only zero-hosting option that retains unattended update checks.
Its tradeoff is credential provisioning and rotation on each authorized
appliance.

## Option 2: manual signed update

An authorized person downloads the channel pointer, signed manifest,
signature, and listed package assets from GitHub, places them together on
encrypted removable media, and transfers them to the appliance. Check and
install without any GitHub credential:

```bash
sudo recovera-upgrade check --channel-file /media/recovera/stable.json \
  --source-dir /media/recovera/release
sudo recovera-upgrade install --channel-file /media/recovera/stable.json \
  --source-dir /media/recovera/release
```

The same pinned public key, monotonic sequence, signature, package policy, and
SHA-256 checks apply. The removable media does not need to be trusted, but the
operator must obtain the correct channel pointer and all assets for the same
release.

## OVA access

Keep the repository private and grant selected people read access through
their GitHub accounts. They sign in to GitHub only to download the OVA; the OVA
must contain no GitHub token. Alternatively, send the published OVA and its
`.sha256` file through an approved private file-transfer method. Always verify
the SHA-256 value against the signed or independently communicated release
record before import.

## Gateway migration

For multiple appliances, use the [active-active update gateway
cluster](update-gateway.md). It replaces GitHub credential distribution, not
release-signature verification. Until gateways are deployed, use root-only
per-appliance tokens for automatic checks or manual signed update media for
appliances that must hold no online credential.
