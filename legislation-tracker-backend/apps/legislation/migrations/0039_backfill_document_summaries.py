from django.db import migrations, models
from django.db.models.functions import Coalesce, NullIf


def backfill(apps, editor):
    from apps.legislation.source_summary import document_summary

    Document = apps.get_model("legislation", "BillDocument")
    docs = Document.objects.using(editor.connection.alias)
    source = Coalesce(
        NullIf("extracted_text", models.Value("")),
        "raw_text",
        models.Value(""),
        output_field=models.TextField(),
    )
    last = 0
    while True:
        rows = list(
            docs.filter(pk__gt=last)
            .exclude(summary_text_hash=models.F("reader_text_hash"))
            .order_by("pk")
            .values_list("pk", "reader_text_hash", source)[:16]
        )
        if not rows:
            return
        for pk, digest, text in rows:
            docs.filter(pk=pk, reader_text_hash=digest).update(
                summary_text_hash=digest,
                stored_text_summary=document_summary(text),
            )
        last = rows[-1][0]


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("legislation", "0038_billdocument_stored_text_summary_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
