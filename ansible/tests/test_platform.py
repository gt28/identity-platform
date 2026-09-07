"""Offline contract tests for the actual Ansible expressions and templates.

These do not substitute for the disposable Ubuntu VM smoke workflow.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ENV = Environment(undefined=StrictUndefined)
ENV.filters.update(FilterModule().filters())
ENV.tests.update(TestModule().tests())


def document(path):
    return yaml.safe_load((ROOT / path).read_text())


def task(path, name):
    items = document(path)
    if path.startswith("playbooks/"):
        items = items[0]["tasks"]
    return next(item for item in items if item["name"] == name)


def evaluate(expression, **context):
    return ENV.compile_expression(expression)(**context)


def facts(distribution="Ubuntu", version="24.04", family="Debian", architecture="x86_64"):
    return {
        "distribution": distribution,
        "distribution_version": version,
        "distribution_major_version": version.split(".")[0],
        "os_family": family,
        "architecture": architecture,
    }


def defaults(role, **context):
    result = {**document(f"roles/{role}/defaults/main.yml"), **context}
    for _ in range(4):
        result = {
            key: ENV.from_string(value).render(result) if isinstance(value, str) else value
            for key, value in result.items()
        }
    return result


class PlatformContracts(unittest.TestCase):
    def test_smoke_password_meets_realm_complexity_policy(self):
        generation = next(
            t["ansible.builtin.copy"]
            for t in document("tests/smoke-user.yml")[0]["tasks"]
            if "ansible.builtin.copy" in t
        )
        password = ENV.from_string(generation["content"]).render(lookup=lambda *args: "x" * 40)
        self.assertGreaterEqual(len(password), 14)
        for pattern in [r"[a-z]", r"[A-Z]", r"[0-9]", r"[^a-zA-Z0-9]"]:
            self.assertRegex(password, pattern)
        self.assertIs(generation["force"], False)
        self.assertEqual(generation["mode"], "0600")

    @unittest.skipUnless(shutil.which("docker"), "Docker CLI with Compose is not installed")
    def test_rendered_compose_passes_real_cli_validation(self):
        template = ENV.from_string((ROOT / "roles/keycloak/templates/compose.yml.j2").read_text())
        with tempfile.TemporaryDirectory(prefix="identity-compose-test-") as directory:
            (Path(directory) / ".env").write_text(
                "KEYCLOAK_ADMIN_USER=validation\n"
                "KEYCLOAK_ADMIN_PASSWORD=compose-validation-only\n"
                "KEYCLOAK_DB_PASSWORD=compose-validation-only\n"
            )
            for candidate in [facts(), facts("Rocky", "9.8", "RedHat")]:
                for local_database in [True, False]:
                    context = defaults(
                        "keycloak",
                        ansible_facts=candidate,
                        keycloak_manage_postgres=local_database,
                    )
                    result = subprocess.run(
                        [
                            "docker",
                            "compose",
                            "--project-directory",
                            directory,
                            "-f",
                            "-",
                            "config",
                            "--quiet",
                        ],
                        input=template.render(context),
                        text=True,
                        capture_output=True,
                        timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_docker_sources_require_migration(self):
        guard = task(
            "roles/docker_engine/tasks/preflight.yml",
            "Require migration of legacy Docker APT sources before scoped trust changes",
        )["ansible.builtin.assert"]["that"][0]
        self.assertTrue(evaluate(guard, docker_legacy_apt_sources={"matched": 0}))
        self.assertFalse(evaluate(guard, docker_legacy_apt_sources={"matched": 1}))

    def test_support_matrix(self):
        gates = [
            document("roles/system_baseline/tasks/preflight.yml")[0],
            document("roles/docker_engine/tasks/preflight.yml")[0],
        ]
        cases = [
            (facts(), True),
            (facts(architecture="aarch64"), True),
            (facts("Rocky", "9.8", "RedHat"), True),
            (facts("RedHat", "9.6", "RedHat"), True),
            (facts("AlmaLinux", "9.6", "RedHat"), True),
            (facts(version="22.04"), False),
            (facts(version="26.04"), False),
            (facts("Debian", "12", "Debian"), False),
            (facts("openEuler", "24.03", "RedHat"), False),
            (facts("Rocky", "8.10", "RedHat"), False),
        ]
        for candidate, expected in cases:
            for gate in gates:
                with self.subTest(candidate=candidate, gate=gate["name"]):
                    accepted = all(
                        evaluate(check, ansible_facts=candidate)
                        for check in gate["ansible.builtin.assert"]["that"]
                    )
                    self.assertEqual(accepted, expected)

    def test_docker_rejects_unvalidated_architecture(self):
        checks = document("roles/docker_engine/tasks/preflight.yml")[0]["ansible.builtin.assert"][
            "that"
        ]
        self.assertFalse(
            all(evaluate(check, ansible_facts=facts(architecture="riscv64")) for check in checks)
        )

    def test_distribution_dispatch_uses_explicit_file_parameter(self):
        for role in ["system_baseline", "docker_engine"]:
            dispatch = next(
                t["ansible.builtin.include_tasks"]
                for t in document(f"roles/{role}/tasks/main.yml")
                if "ansible.builtin.include_tasks" in t
            )
            for candidate, expected in [
                (facts(), "Ubuntu.yml"),
                (facts("Rocky", "9.8", "RedHat"), "RedHat.yml"),
            ]:
                self.assertEqual(
                    ENV.from_string(dispatch["file"]).render(ansible_facts=candidate), expected
                )

    def test_os_specific_security_and_service_names(self):
        ubuntu = document("roles/system_baseline/vars/Ubuntu.yml")
        el9 = document("roles/system_baseline/vars/RedHat.yml")
        self.assertEqual(ubuntu["ssh_service"], "ssh")
        self.assertEqual(el9["ssh_service"], "sshd")
        self.assertIn("chrony", ubuntu["services"])
        self.assertIn("apparmor", ubuntu["services"])
        self.assertIn("chronyd", el9["services"])
        self.assertIn("auditd", ubuntu["packages"])
        self.assertNotIn("python3-libselinux", ubuntu["packages"])
        self.assertIn("python3-libselinux", el9["packages"])
        self.assertNotIn(
            "ansible.builtin.dnf", str(document("roles/system_baseline/tasks/Ubuntu.yml"))
        )

    def test_rejects_unsafe_ssh_bootstrap(self):
        checks = document("roles/system_baseline/tasks/preflight.yml")[1]["ansible.builtin.assert"][
            "that"
        ]
        for user, keys, expected in [
            ("ansible", ["ssh-ed25519 AAAAtest test@example.test"], True),
            ("root", ["ssh-ed25519 AAAAtest"], False),
            ("ansible", [], False),
            ("ansible", ["REPLACE_WITH_APPROVED_KEY"], False),
            ("bad/user", ["ssh-ed25519 AAAAtest"], False),
        ]:
            with self.subTest(user=user, keys=keys):
                self.assertEqual(
                    all(
                        evaluate(c, system_admin_user=user, system_admin_public_keys=keys)
                        for c in checks
                    ),
                    expected,
                )

    def test_ufw_guard(self):
        import base64

        guard = task(
            "roles/system_baseline/tasks/preflight.yml",
            "Reject an enabled UFW configuration before installing firewalld",
        )
        check = guard["ansible.builtin.assert"]["that"][0]
        for text, expected in [
            ("ENABLED=yes\n", False),
            ('ENABLED="yes"\n', False),
            ("# ENABLED=yes\nENABLED=no\n", True),
        ]:
            content = base64.b64encode(text.encode()).decode()
            self.assertEqual(
                evaluate(check, system_ufw_content={"content": content}, **guard["vars"]), expected
            )

    def test_ssh_dropin_precedes_cloud_init(self):
        config = task(
            "roles/system_baseline/tasks/main.yml", "Install SSH daemon hardening configuration"
        )
        self.assertEqual(
            Path(config["ansible.builtin.template"]["dest"]).name, "00-identity-hardening.conf"
        )
        checks = task(
            "roles/system_baseline/tasks/main.yml", "Require effective key-only SSH authentication"
        )["ansible.builtin.assert"]["that"]
        self.assertFalse(
            all(
                evaluate(c, system_sshd_effective={"stdout_lines": ["passwordauthentication yes"]})
                for c in checks
            )
        )

    def test_docker_repository_and_key_are_distribution_specific(self):
        for candidate, suffix, fingerprint in [
            (facts(), "ubuntu", "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"),
            (facts("Rocky", "9.8", "RedHat"), "centos", "060A61C51B558A7F742B77AAC52FEB6B621E9F35"),
        ]:
            result = defaults("docker_engine", ansible_facts=candidate)
            self.assertEqual(
                result["docker_repository_base_url"], f"https://download.docker.com/linux/{suffix}"
            )
            self.assertEqual(
                result["docker_gpg_key_url"], f"https://download.docker.com/linux/{suffix}/gpg"
            )
            self.assertEqual(result["docker_gpg_fingerprint"], fingerprint)

    def test_docker_key_guard_rejects_unapproved_key(self):
        check = task(
            "roles/docker_engine/tasks/Ubuntu.yml", "Require the approved Docker APT signing key"
        )["ansible.builtin.assert"]["that"][0]
        for fingerprint, expected in [("APPROVED", True), ("WRONG", False)]:
            line = "fpr:::::::::" + fingerprint + ":"
            self.assertEqual(
                evaluate(
                    check,
                    docker_apt_key_info={"stdout_lines": [line]},
                    docker_gpg_fingerprint="APPROVED",
                ),
                expected,
            )

    def test_apt_repository_architecture_and_scoped_trust(self):
        config = task(
            "roles/docker_engine/tasks/Ubuntu.yml",
            "Configure the Docker Noble APT repository with scoped trust",
        )["ansible.builtin.deb822_repository"]
        self.assertEqual(config["suites"], ["noble"])
        self.assertEqual(config["signed_by"], "/etc/apt/keyrings/docker.asc")
        for arch, expected in [("x86_64", "amd64"), ("aarch64", "arm64")]:
            self.assertEqual(
                ENV.from_string(config["architectures"][0]).render(
                    ansible_facts=facts(architecture=arch)
                ),
                expected,
            )

    def test_existing_container_packages_require_opt_in(self):
        check = task(
            "roles/docker_engine/tasks/Ubuntu.yml",
            "Require explicit approval before replacing existing container packages",
        )["ansible.builtin.assert"]["that"][0]
        for packages, approved, expected in [
            ([], False, True),
            (["containerd"], False, False),
            (["docker.io"], True, True),
        ]:
            self.assertEqual(
                evaluate(
                    check,
                    docker_conflicting_packages=packages,
                    docker_remove_conflicting_packages=approved,
                ),
                expected,
            )
        self.assertIs(
            document("roles/docker_engine/defaults/main.yml")["docker_remove_conflicting_packages"],
            False,
        )

    def test_compose_version_gate(self):
        check = task("roles/docker_engine/tasks/main.yml", "Require a supported Compose plugin")[
            "ansible.builtin.assert"
        ]["that"][0]
        for version, expected in [
            ("v2.18.0", True),
            ("2.39.1\n", True),
            ("5.0.0", True),
            ("1.29.2", False),
            ("2.17.0", False),
        ]:
            self.assertEqual(
                evaluate(
                    check,
                    docker_compose_version={"stdout": version},
                    docker_compose_min_version="2.18.0",
                ),
                expected,
            )

    def test_compose_preserves_selinux_only_on_el9(self):
        template = ENV.from_string((ROOT / "roles/keycloak/templates/compose.yml.j2").read_text())
        for candidate, suffix in [(facts(), ":ro"), (facts("Rocky", "9.8", "RedHat"), ":ro,Z")]:
            for local_database in [True, False]:
                context = defaults(
                    "keycloak", ansible_facts=candidate, keycloak_manage_postgres=local_database
                )
                compose = yaml.safe_load(template.render(context))
                mounts = compose["services"]["keycloak"]["volumes"]
                self.assertIn("./tls:/opt/keycloak/conf/tls" + suffix, mounts)
                self.assertIn("./truststores:/opt/keycloak/conf/truststores" + suffix, mounts)
                self.assertEqual("postgres" in compose["services"], local_database)
                self.assertTrue(compose["services"]["keycloak"]["read_only"])

    def test_verification_parses_compose_json_array_and_json_lines(self):
        expression = task(
            "playbooks/verify.yml", "Parse Compose service status as structured data"
        )["ansible.builtin.set_fact"]["keycloak_verify_services"]
        expected = [{"Service": "keycloak", "State": "running", "Health": "healthy"}]
        for stdout in [json.dumps(expected), json.dumps(expected[0])]:
            rendered = ENV.from_string(expression).render(
                keycloak_compose_ps={"stdout": stdout, "stdout_lines": stdout.splitlines()}
            )
            self.assertEqual(yaml.safe_load(rendered), expected)

    def test_verification_rejects_stopped_unhealthy_or_missing_services(self):
        checks = task(
            "playbooks/verify.yml", "Require expected Compose services to be healthy and running"
        )["ansible.builtin.assert"]["that"]
        for state, health, expected in [
            ("running", "healthy", True),
            ("exited", "healthy", False),
            ("running", "unhealthy", False),
        ]:
            services = [{"Service": "keycloak", "State": state, "Health": health}]
            self.assertEqual(
                all(
                    evaluate(c, item="keycloak", keycloak_verify_services=services) for c in checks
                ),
                expected,
            )
        self.assertFalse(
            all(evaluate(c, item="keycloak", keycloak_verify_services=[]) for c in checks)
        )


if __name__ == "__main__":
    unittest.main()
