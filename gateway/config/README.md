# Gateway secrets

Create these deployment-local files; only `revocations.json` is tracked:

- `github-token`: fine-grained GitHub token with read-only Contents access to
  the private Recovera repository.
- `access-signers`: copy of `gateway/keys/recovera-gateway-access-signers`
  (the deployment helper creates this copy).
- `revocations.json`: token identifiers that every gateway must reject.

`github-token` is ignored by Git. Set mode `0600`. Never place the Recovera
release-signing or recovery private key on a gateway.
