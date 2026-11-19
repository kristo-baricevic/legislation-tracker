from io import StringIO

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings


@override_settings(CONGRESS_API_KEY="test", FEC_API_KEY="test", LLM_ENHANCEMENTS_ENABLED=False)
class DockerStartupTests(SimpleTestCase):
    def test_configured_ingestion_allows_explicitly_disabled_enhancements(self):
        output = StringIO()
        call_command("check_docker_startup", stdout=output)
        self.assertIn("Docker configuration ready", output.getvalue())

    @override_settings(CONGRESS_API_KEY=" ")
    def test_missing_ingestion_key_blocks_startup(self):
        with self.assertRaisesMessage(CommandError, "CONGRESS_API_KEY"):
            call_command("check_docker_startup")

    @override_settings(FEC_API_KEY="")
    def test_missing_research_key_blocks_startup(self):
        with self.assertRaisesMessage(CommandError, "FEC_API_KEY"):
            call_command("check_docker_startup")

    @override_settings(LLM_ENHANCEMENTS_ENABLED=True, LLM_CREDENTIAL_ENCRYPTION_KEYS="",
                       LLM_CREDENTIAL_ACTIVE_KEY_ID="")
    def test_enabled_enhancements_without_encryption_keys_block_startup(self):
        with self.assertRaisesMessage(CommandError, "missing_encryption_keys"):
            call_command("check_docker_startup")
