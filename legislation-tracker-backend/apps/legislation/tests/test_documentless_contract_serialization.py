from django.test import SimpleTestCase
from django.utils import timezone

from apps.legislation.models import BillContract
from apps.legislation.serializers import BillContractSerializer, BillContractSummarySerializer


class DocumentlessContractSerializationTests(SimpleTestCase):
    def test_documentless_contract_keeps_nullable_version_label(self):
        contract = BillContract(
            id=31773, bill_id=16743, document=None,
            schema_version="1.1-deterministic", contract_hash="test-hash",
            contract_json={}, computed_at=timezone.now(),
        )
        contract._prefetched_objects_cache = {"evidence_spans": []}
        for serializer in (BillContractSerializer, BillContractSummarySerializer):
            with self.subTest(serializer=serializer.__name__):
                data = serializer(contract).data
                self.assertIn("document_version_label", data)
                self.assertIsNone(data["document_version_label"])
                self.assertIsNone(data["document"])
