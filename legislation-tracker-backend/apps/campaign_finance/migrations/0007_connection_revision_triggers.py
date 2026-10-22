from django.db import migrations


TABLES = (
    "congress_representative", "congress_billcosponsor", "congress_vote", "congress_voterecord",
    "legislation_bill", "legislation_billtopic", "legislation_topic",
    "campaign_finance_financesnapshot", "campaign_finance_financetransaction",
    "campaign_finance_contributor", "campaign_finance_contributoridentity",
    "campaign_finance_representativecandidate", "campaign_finance_candidatecommittee",
    "campaign_finance_campaigncommittee",
)


def install(apps, editor):
    vendor = editor.connection.vendor
    if vendor == "postgresql":
        editor.execute("""CREATE FUNCTION research_bump_connections() RETURNS trigger AS $$
            BEGIN UPDATE campaign_finance_connectionrevision SET generation = generation + 1 WHERE id = 1; RETURN NULL; END;
            $$ LANGUAGE plpgsql""")
        for table in TABLES:
            editor.execute(f"CREATE TRIGGER research_connections_changed AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION research_bump_connections()")
    elif vendor == "sqlite":
        for table in TABLES:
            for event in ("INSERT", "UPDATE", "DELETE"):
                editor.execute(f"CREATE TRIGGER research_changed_{table}_{event} AFTER {event} ON {table} BEGIN UPDATE campaign_finance_connectionrevision SET generation = generation + 1 WHERE id = 1; END")


def uninstall(apps, editor):
    if editor.connection.vendor == "postgresql":
        for table in TABLES:
            editor.execute(f"DROP TRIGGER IF EXISTS research_connections_changed ON {table}")
        editor.execute("DROP FUNCTION IF EXISTS research_bump_connections()")
    elif editor.connection.vendor == "sqlite":
        for table in TABLES:
            for event in ("INSERT", "UPDATE", "DELETE"):
                editor.execute(f"DROP TRIGGER IF EXISTS research_changed_{table}_{event}")


class Migration(migrations.Migration):
    dependencies = [
        ("campaign_finance", "0006_connectionrevision_financesnapshot_committee_links"),
        ("congress", "0011_representative_terms"),
        ("legislation", "0019_billdocument_source_purpose"),
    ]
    operations = [migrations.RunPython(install, uninstall)]
