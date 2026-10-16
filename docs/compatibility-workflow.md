# Reference-release compatibility workflow

Recovera uses sanitized appliance inventories to evaluate a new reference
release without copying application content, credentials, certificates,
customer data, or machine identity into the repository. The reports contain
package metadata, service-unit state, file metadata, and cryptographic digests.

This workflow is a compatibility aid, not an authorization to copy or
redistribute third-party software. Confirm the applicable license before using
any reference image or package.

## Establish the baseline

Copy the repository's collector and policy to an isolated, licensed reference
VM. Run it once against the currently supported release:

```bash
sudo python3 collect-baseline.py \
  --label reference-current \
  --policy collection-policy.json \
  --output reference-current.json
```

The collector does not inspect file contents beyond calculating SHA-256
digests. It excludes common credential stores, password databases, SSH keys,
private keys, tokens, and database files. It does not record hostname, IP
address, disk serials, users, process arguments, environment variables, or
network connections. Output permissions are restricted to the invoking user.

Review every report before moving it off the isolated VM. Store reports in
`compatibility/reports/`, which is intentionally ignored by Git.

## Evaluate a new release

Deploy the new image as a separate disposable VM and collect a second report:

```bash
sudo python3 collect-baseline.py \
  --label reference-candidate \
  --policy collection-policy.json \
  --output reference-candidate.json
```

Compare the two reports on the development workstation:

```bash
python3 tools/compatibility/compare-baselines.py \
  --before compatibility/reports/reference-current.json \
  --after compatibility/reports/reference-candidate.json \
  --json compatibility/reports/candidate-diff.json \
  --markdown compatibility/reports/candidate-diff.md
```

The comparison marks removals as high-attention because removed packages,
units, and application surfaces are the most likely to break an overlay. A
version change is not automatically considered safe; maintainers must compare
the report with `compatibility/recovera-overlay.json` and determine whether an
independent Recovera change is required.

## Qualification gates

Before adopting a compatibility change:

1. Confirm the reference release and both reports came from clean, disposable
   VMs rather than production appliances.
2. Review package maintainer scripts and schema migrations in the licensed
   evaluation environment; do not commit their contents.
3. Map every changed or removed surface against the Recovera overlay manifest.
4. Implement Recovera changes independently and update the overlay manifest
   when a contract changes.
5. Build a signed Recovera candidate update.
6. Test registration, protection, backup, verification, restore, full and
   incremental replication, update, health validation, and rollback.
7. Promote only the signed Recovera package or image through its normal update
   channel. Never point production appliances at the reference update source.

The first real reference update should be treated as a calibration run. It will
show which surfaces are noisy and which additional contracts need explicit
coverage, after which the collection policy can be tightened rather than
broadened indiscriminately.
