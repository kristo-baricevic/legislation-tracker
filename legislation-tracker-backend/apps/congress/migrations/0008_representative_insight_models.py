import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("congress", "0007_vote_scope_and_identity")]

    operations = [
        migrations.CreateModel(name="Committee", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("system_code", models.CharField(max_length=32, unique=True)),
            ("name", models.CharField(max_length=255)),
            ("chamber", models.CharField(choices=[("house", "House"), ("senate", "Senate"), ("joint", "Joint")], max_length=16)),
            ("committee_type", models.CharField(blank=True, default="", max_length=32)),
            ("website_url", models.URLField(blank=True, default="", max_length=1024)),
            ("is_current", models.BooleanField(default=True)),
            ("source_updated_at", models.DateTimeField(blank=True, null=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="subcommittees", to="congress.committee")),
        ], options={"db_table": "congress_committee"}),
        migrations.CreateModel(name="CommitteeMembership", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("congress", models.PositiveSmallIntegerField()), ("rank", models.PositiveSmallIntegerField(blank=True, null=True)),
            ("role", models.CharField(choices=[("member", "Member"), ("chair", "Chair"), ("ranking_member", "Ranking member"), ("vice_chair", "Vice chair"), ("other", "Other")], default="member", max_length=24)),
            ("party_side", models.CharField(blank=True, default="", max_length=32)), ("source_name", models.CharField(max_length=32)), ("source_code", models.CharField(max_length=32)),
            ("is_current", models.BooleanField(default=True)), ("source_updated_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("committee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="congress.committee")),
            ("representative", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="committee_memberships", to="congress.representative")),
        ], options={"db_table": "congress_committeemembership"}),
        migrations.CreateModel(name="BillCommittee", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("relationship_type", models.CharField(default="referred", max_length=32)), ("activity_name", models.CharField(blank=True, default="", max_length=255)), ("source_name", models.CharField(blank=True, default="congress", max_length=32)), ("source_code", models.CharField(blank=True, default="", max_length=32)), ("source_updated_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("bill", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="committee_relationships", to="legislation.bill")), ("committee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bill_relationships", to="congress.committee")),
        ], options={"db_table": "congress_billcommittee"}),
        migrations.CreateModel(name="BillCosponsor", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("sponsorship_date", models.DateField(blank=True, null=True)), ("is_original_cosponsor", models.BooleanField(default=False)), ("withdrawn_at", models.DateTimeField(blank=True, null=True)), ("source_updated_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("bill", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cosponsors", to="legislation.bill")), ("representative", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cosponsored_bills", to="congress.representative")),
        ], options={"db_table": "congress_billcosponsor"}),
        migrations.AddConstraint(model_name="committeemembership", constraint=models.UniqueConstraint(fields=("committee", "representative", "congress"), name="congress_committee_member_congress_uniq")),
        migrations.AddIndex(model_name="committee", index=models.Index(fields=["chamber", "is_current"], name="congress_co_chamber_227de2_idx")),
        migrations.AddIndex(model_name="committeemembership", index=models.Index(fields=["representative", "congress", "is_current"], name="cong_mem_rep_scope_idx")),
        migrations.AddIndex(model_name="committeemembership", index=models.Index(fields=["committee", "congress", "is_current"], name="cong_mem_comm_scope_idx")),
        migrations.AddConstraint(model_name="billcommittee", constraint=models.UniqueConstraint(fields=("bill", "committee", "relationship_type"), name="congress_bill_committee_relationship_uniq")),
        migrations.AddIndex(model_name="billcommittee", index=models.Index(fields=["bill", "relationship_type"], name="congress_bi_bill_id_231305_idx")),
        migrations.AddConstraint(model_name="billcosponsor", constraint=models.UniqueConstraint(fields=("bill", "representative"), name="congress_bill_cosponsor_uniq")),
        migrations.AddIndex(model_name="billcosponsor", index=models.Index(fields=["representative", "withdrawn_at"], name="cong_cosponsor_rep_idx")),
    ]
