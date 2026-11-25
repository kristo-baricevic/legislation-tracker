"""Dedicated execution lanes; the default queue only coordinates work."""

STAGE_QUEUES = {
    kind: kind
    for kind in (
        "bill",
        "bill_versions",
        "bill_votes",
        "bill_relationships",
        "document_download",
        "document_contract",
        "metadata_contract",
        "topic_update",
        "search_index",
        "representative_detail",
        "roll_call_vote",
        "committee_roster",
    )
}
STAGE_QUEUES.update(representative_research="research", similarity="similarity")

DIRECT_TASK_QUEUES = {
    "apps.ingestion.tasks.process_bill": "bill",
    "apps.ingestion.tasks.process_bill_versions": "bill_versions",
    "apps.ingestion.tasks.process_bill_votes": "bill_votes",
    "apps.ingestion.tasks.download_document": "document_download",
    "apps.ingestion.tasks.sync_committee_memberships": "committee_roster",
    "apps.ingestion.tasks.sync_representatives": "representative_detail",
    "apps.ingestion.tasks.poll_congress": "discovery",
    "apps.ingestion.tasks.poll_tracked_bills": "discovery",
    "apps.ingestion.tasks.discover_roll_calls": "vote_discovery",
    "apps.legislation.tasks.generate_contract": "document_contract",
    "apps.legislation.tasks.generate_contract_for_bill": "metadata_contract",
    "apps.legislation.tasks.update_topics": "topic_update",
}
