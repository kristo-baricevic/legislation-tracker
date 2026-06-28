from apps.ingestion import congress_client


def test_bill_text_list_preserves_top_level_version_url(monkeypatch):
    def fake_request(method, path, params=None):
        return {
            "textVersions": [
                {
                    "type": "Introduced",
                    "url": "https://example.test/bills/hr1.xml",
                }
            ]
        }

    monkeypatch.setattr(congress_client, "_request", fake_request)
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)

    versions = congress_client.bill_text_list(119, "hr", "1")

    assert versions == [
        {
            "version_label": "Introduced",
            "url": "https://example.test/bills/hr1.xml",
        }
    ]

