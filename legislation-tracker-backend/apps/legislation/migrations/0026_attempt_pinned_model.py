from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('legislation', '0025_reader_lookup_digests')]
    operations = [migrations.AddField(
        model_name='billenhancementattempt', name='pinned_model',
        field=models.CharField(max_length=255, blank=True, default=''),
    )]
