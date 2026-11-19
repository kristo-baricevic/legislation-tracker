"""Run with: rtk proxy python3 -m unittest discover -s scripts -p 'test_*.py'."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DockerStartupTests(unittest.TestCase):
    def config(self, **overrides):
        values = dict(DJANGO_SECRET_KEY="test-only-secret", CONGRESS_API_KEY="test-congress",
                      FEC_API_KEY="test-fec", LLM_ENHANCEMENTS_ENABLED="False")
        values.update(overrides)
        with tempfile.NamedTemporaryFile(mode="w") as env_file:
            env_file.write("\n".join(f"{k}={v}" for k, v in values.items()))
            env_file.flush()
            env = {k: v for k, v in os.environ.items() if k not in values}
            env["DOCKER_ENV_FILE"] = env_file.name
            return subprocess.run(
                ["rtk", "proxy", "docker", "compose", "--env-file", env_file.name,
                 "-f", str(ROOT / "compose.yaml"), "config", "--format", "json"],
                env=env, capture_output=True, text=True,
            )

    def test_default_startup_consumes_all_queues_with_shared_configuration(self):
        result = self.config()
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        for name, queue in [("worker", "celery"), ("research-worker", "research"),
                            ("enhancement-worker", "enhancements")]:
            service = services[name]
            command = service["command"]
            self.assertEqual(command[command.index("-Q") + 1], queue)
            self.assertNotIn("profiles", service)
            self.assertEqual(service["environment"], services["api"]["environment"])
            self.assertEqual(service["depends_on"]["migrate"]["condition"],
                             "service_completed_successfully")
            self.assertEqual(service["restart"], "unless-stopped")
        self.assertIn("beat", services)
        self.assertIn("migrate", services)
        self.assertIn("preflight", services)
        self.assertIn("client", services)
        for name in ("postgres", "redis", "minio"):
            self.assertTrue(services[name]["volumes"])
        self.assertEqual(services["migrate"]["depends_on"]["preflight"]["condition"],
                         "service_completed_successfully")

    def test_missing_ingestion_key_stops_configuration(self):
        result = self.config(CONGRESS_API_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONGRESS_API_KEY", result.stderr)

    def test_missing_research_key_stops_configuration(self):
        result = self.config(FEC_API_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FEC_API_KEY", result.stderr)

    def test_missing_secret_stops_configuration(self):
        result = self.config(DJANGO_SECRET_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_enhancement_enablement_must_be_explicit(self):
        result = self.config(LLM_ENHANCEMENTS_ENABLED="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LLM_ENHANCEMENTS_ENABLED", result.stderr)

    def test_adoption_uses_external_volumes_without_creating_replacements(self):
        result = self.config(EXISTING_VOLUMES="true", POSTGRES_VOLUME="existing-postgres",
                             REDIS_VOLUME="existing-redis", MINIO_VOLUME="existing-documents")
        self.assertEqual(result.returncode, 0, result.stderr)
        volumes = json.loads(result.stdout)["volumes"]
        for key, name in [("postgres_data", "existing-postgres"),
                          ("redis_data", "existing-redis"), ("minio_data", "existing-documents")]:
            self.assertTrue(volumes[key]["external"])
            self.assertEqual(volumes[key]["name"], name)


if __name__ == "__main__":
    unittest.main()
