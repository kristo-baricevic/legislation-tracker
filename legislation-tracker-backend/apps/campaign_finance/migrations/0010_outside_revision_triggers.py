import uuid
from django.db import migrations, models
import django.db.models.deletion

# Resolve both old and new owners, including reassignment and bulk writes.
OWNERS = {
    "campaign_finance_financesnapshot": "{row}.representative_id",
    "research_researchrun": "{row}.representative_id",
    "campaign_finance_outsidespendingscan": "(SELECT representative_id FROM campaign_finance_financesnapshot WHERE id = {row}.snapshot_id)",
    "campaign_finance_outsidespendingtotal": "(SELECT s.representative_id FROM campaign_finance_financesnapshot s JOIN campaign_finance_outsidespendingscan c ON c.snapshot_id = s.id WHERE c.id = {row}.scan_id)",
}


def install(apps, editor):
    for index, (table, owner) in enumerate(OWNERS.items()):
        for event in ("INSERT", "UPDATE", "DELETE"):
            references = ["NEW"] if event == "INSERT" else ["OLD"] if event == "DELETE" else ["OLD", "NEW"]
            owners = ", ".join(owner.format(row=ref) for ref in references)
            update = f"UPDATE campaign_finance_outsidespendingrevision SET generation = generation + 1 WHERE representative_id IN ({owners});"
            name = f"outside_revision_{index}_{event.lower()}"
            if editor.connection.vendor == "postgresql":
                editor.execute(f"CREATE FUNCTION {name}() RETURNS trigger AS $$ BEGIN {update} RETURN NULL; END; $$ LANGUAGE plpgsql")
                editor.execute(f"CREATE TRIGGER {name} AFTER {event} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()")
            elif editor.connection.vendor == "sqlite":
                editor.execute(f"CREATE TRIGGER {name} AFTER {event} ON {table} BEGIN {update} END")


def uninstall(apps, editor):
    for index, table in enumerate(OWNERS):
        for event in ("insert", "update", "delete"):
            name = f"outside_revision_{index}_{event}"
            if editor.connection.vendor == "postgresql":
                editor.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                editor.execute(f"DROP FUNCTION IF EXISTS {name}()")
            elif editor.connection.vendor == "sqlite":
                editor.execute(f"DROP TRIGGER IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [("campaign_finance", "0009_candidate_reporting_periods")]
    operations = [
        migrations.CreateModel(name="OutsideSpendingRevision", fields=[
            ("representative", models.OneToOneField(primary_key=True, serialize=False, on_delete=django.db.models.deletion.CASCADE, to="congress.representative")),
            ("generation", models.PositiveBigIntegerField(default=0)),
            ("epoch", models.UUIDField(default=uuid.uuid4)),
        ]),
        migrations.RunPython(install, uninstall),
    ]
