import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RecoveraNobleCompatibilityTests(unittest.TestCase):
    def test_setup_supports_jammy_and_noble_bundles(self):
        setup = (ROOT / "setup" / "setup.sh").read_text(encoding="utf-8")
        self.assertIn("22.04|24.04) ;;", setup)
        self.assertIn('siris-os-2_*ubuntu${VERSION_ID}_*.deb', setup)
        self.assertIn('systemctl restart "$(php_fpm_unit)"', setup)
        self.assertNotIn("systemctl restart php8.3-fpm", setup)
        self.assertNotIn("systemctl restart php8.1-fpm", setup)
        # Noble-only runtime fixes never run on a 22.04 bundle.
        engine = setup[setup.index("p75_protection_engine() {"):setup.index("p75_noble_runtime() {")]
        self.assertIn('if [ "${VERSION_ID:-}" = 24.04 ]; then', engine)
        self.assertNotIn("dnsmasq", engine)
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("22.04|24.04) ;;", installer)

    def test_package_update_never_restarts_restore_services(self):
        builder = (ROOT / "tools" / "build-recovera-appliance-deb.sh").read_text(encoding="utf-8")
        postinst = builder[builder.index("cat > \"$stage/DEBIAN/postinst\""):]
        self.assertNotIn("restart target.service", postinst)
        self.assertNotIn("restart dnsmasq", postinst)
        self.assertNotIn('"$stage/etc/dnsmasq.d', builder)
        self.assertIn('if [ "${VERSION_ID:-}" = 24.04 ]; then', postinst)
        self.assertIn("php8.1-fpm | php8.3-fpm", builder)

    def test_source_package_sanitizer_removes_noble_incompatible_driver(self):
        sanitizer = (ROOT / "tools" / "sanitize-source-package.py").read_text(encoding="utf-8")
        self.assertIn("usr/lib64/libvirt/connection-driver/libvirt_driver_libxl.so", sanitizer)
        self.assertIn('rly_source = "            rly-client.service', sanitizer)
        self.assertIn("pip install --no-input --no-deps npyscreen==4.10.5", sanitizer)
        self.assertIn("venv --system-site-packages", sanitizer)
        self.assertIn("salt-minion", (ROOT / "setup" / "prune-packages.txt").read_text())

    def test_restore_runtime_has_persistent_noble_boot_fixes(self):
        setup = (ROOT / "setup" / "setup.sh").read_text(encoding="utf-8")
        target = (ROOT / "setup" / "target-recovera.conf").read_text(encoding="utf-8")
        dnsmasq = (ROOT / "setup" / "recovera-dnsmasq.conf").read_text(encoding="utf-8")
        builder = (ROOT / "tools" / "build-recovera-appliance-deb.sh").read_text(encoding="utf-8")
        self.assertIn("ExecStartPre=/sbin/modprobe target_core_mod", target)
        self.assertIn("ExecStartPost=\n", target)
        self.assertIn("ExecStop=/usr/bin/targetctl clear", target)
        self.assertIn("except-interface=lo", dnsmasq)
        self.assertIn("php8.3-fpm", builder)
        self.assertIn("target-recovera.conf", builder)
        self.assertIn("target.service.d/zz-recovera.conf", builder)
        bundler = (ROOT / "tools" / "make-bundle.sh").read_text(encoding="utf-8")
        self.assertIn('rm -f "$B"/debs/recovera-appliance_*.deb', bundler)
        self.assertIn('"$B/upgrade/recovera-upgrade"', bundler)
        self.assertIn('"$B/isolation/recovera-cloud-isolation"', bundler)
        isolation_units = (ROOT / "setup" / "isolation" / "cloud-units.txt").read_text(encoding="utf-8")
        self.assertIn("datto-hva-iscsi-tls-configure.service", isolation_units)
        self.assertIn("127.0.1.1", setup)
        self.assertIn("recovera-dnsmasq.conf", builder)

    def test_branding_rebuilds_flat_layout_route_cache(self):
        setup = (ROOT / "setup" / "setup.sh").read_text(encoding="utf-8")
        self.assertIn("app/console.php cache:clear --env=prod", setup)
        self.assertIn("app/console.php cache:warmup --env=prod", setup)

    def test_package_points_existing_configs_at_the_update_gateway(self):
        builder = (ROOT / "tools" / "build-recovera-appliance-deb.sh").read_text(encoding="utf-8")
        self.assertIn("UPDATE_ORIGINS=https://recoveragw.rjproductionsut.com,https://recoveragwb.rjproductionsut.com", builder)
        self.assertIn("s|^UPDATE_ORIGINS=https://recoveragw.rjproductionsut.com$|", builder)
        self.assertIn("grep -q '^UPDATE_ORIGINS=.'", builder)
        self.assertIn("TRANSITION_CHANNEL=jammy-noble-transition", builder)
        self.assertIn("GATEWAY_TOKEN_FILE=/etc/recovera/gateway-token", builder)

    def test_newer_bundle_restages_its_packages(self):
        setup = (ROOT / "setup" / "setup.sh").read_text(encoding="utf-8")
        stage = setup[setup.index("stage_bundle() {"):setup.index("verify_checksums() {")]
        self.assertIn('! cmp -s "$BUNDLE/debs/SHA256SUMS" "$INSTALL_DIR/debs/SHA256SUMS"', stage)


if __name__ == "__main__":
    unittest.main()
