import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.production.yml"


def test_production_compose_blocks_runtime_services_until_migration_succeeds(tmp_path):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose is required to validate the production deployment graph")

    env_file = tmp_path / "production.env"
    env_file.write_text("DJANGO_SECRET_KEY=test-secret\n")
    environment = {
        **os.environ,
        "ENV_FILE": str(env_file),
        "NEXT_PUBLIC_API_URL": "https://app.example.test",
        "POSTGRES_PASSWORD": "test-password",
    }
    result = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "config",
            "--format",
            "json",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    services = json.loads(result.stdout)["services"]
    migrate = services["migrate"]

    assert migrate["restart"] == "no"
    assert migrate["command"] == ["python", "manage.py", "migrate", "--noinput"]
    for service_name in ("api", "worker", "beat"):
        assert (
            services[service_name]["depends_on"]["migrate"]["condition"]
            == "service_completed_successfully"
        )
