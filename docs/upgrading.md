# Upgrading and rollback

Recovera upgrades are performed from a reviewed Git tag. Back up the local
configuration before changing installed files; replicated backup datasets are
not modified by this procedure.

## Upgrade

1. Record the current version and verify appliance health:

   ```bash
   cd ~/recovera
   git describe --tags --always
   sudo /opt/spf-datto/setup.sh verify
   ```

2. Back up Recovera configuration and replication state:

   ```bash
   sudo tar -C / -czf /root/recovera-config-before-upgrade.tgz \
     etc/recovera-peer var/lib/recovera-peer opt/spf-datto/setup.conf
   ```

3. Fetch and check out the intended reviewed release tag. Review the tag and
   compare `setup/release.env` with the published `SHA256SUMS` file:

   ```bash
   git fetch --tags origin
   git checkout v0.5.0
   sha256sum setup/release.env
   ```

4. Stage the release's setup, peer-service, and branding files without
   overwriting the appliance-specific `setup.conf`, then refresh the application
   integration and run verification:

   ```bash
   sudo install -m 0755 setup/setup.sh /opt/spf-datto/setup.sh
   sudo rm -rf /opt/spf-datto/peer /opt/spf-datto/branding
   sudo cp -a setup/peer setup/branding /opt/spf-datto/
   sudo /opt/spf-datto/setup.sh install-peer
   sudo /opt/spf-datto/setup.sh verify
   ```

The full `./install.sh` workflow is intended for fresh Ubuntu installations.
Do not rerun it as an upgrade unless the release notes explicitly require it.

## Rollback

1. Check out the previously recorded tag or commit.
2. Reinstall its peer integration and verify:

   ```bash
   sudo /opt/spf-datto/setup.sh install-peer
   sudo systemctl restart recovera-peer recovera-peer-sync.timer
   sudo /opt/spf-datto/setup.sh verify
   ```

3. Restore `/root/recovera-config-before-upgrade.tgz` only if the release notes
   identify a configuration-format incompatibility. Stop `recovera-peer` before
   restoring it and restart the service afterward.

Never roll back ZFS datasets by deleting recovery points. A software rollback
does not require changing `homePool` or replicated backup data.
