from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("legislation", "0020_billcontract_reader_copy"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.AlterField(
        model_name="billenhancement", name="user",
        field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                related_name="bill_enhancements", to=settings.AUTH_USER_MODEL),
    )]
