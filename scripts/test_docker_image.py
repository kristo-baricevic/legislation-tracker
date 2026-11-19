"""Smoke-test a built backend image without network, credentials, or a database."""
import os
import subprocess
import unittest


class BackendImageTests(unittest.TestCase):
    def test_runtime_dependencies_and_portrait_processing(self):
        script = """
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from packaging.requirements import Requirement
missing = []
for line in Path('/app/requirements/base.txt').read_text().splitlines():
    if not line.strip() or line.startswith('#'):
        continue
    requirement = Requirement(line)
    try:
        installed = version(requirement.name)
    except PackageNotFoundError:
        missing.append(requirement.name)
        continue
    assert requirement.specifier.contains(installed), (requirement.name, installed)
assert not missing, f'Missing runtime dependencies: {missing}'
import os, io, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'
django.setup()
from PIL import Image
from apps.research.portraits import sanitize_portrait
source = io.BytesIO()
Image.new('RGB', (12, 16)).save(source, format='PNG')
body, width, height = sanitize_portrait(source.getvalue())
assert (width, height) == (12, 16)
assert Image.open(io.BytesIO(body)).format == 'PNG'
"""
        result = subprocess.run(
            ["rtk", "proxy", "docker", "run", "--rm", "--network", "none",
             os.environ.get("BACKEND_TEST_IMAGE", "legislation-local-backend"),
             "python", "-c", script], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
