from django.db import migrations, models
from importlib import import_module

revision = import_module('apps.campaign_finance.migrations.0010_outside_revision_triggers')


def safe_reverse(apps, editor):
    from django.db.migrations.exceptions import IrreversibleError
    if apps.get_model('campaign_finance', 'OutsideSpendingTotal').objects.filter(position__in=['24F', '24N']).exists():
        raise IrreversibleError('Archive communication-code records before reverting.')


class Migration(migrations.Migration):
    dependencies = [('campaign_finance', '0011_outside_categories')]
    operations = [
        migrations.RunPython(revision.uninstall, revision.install),
        migrations.AlterField(model_name='outsidespendingtotal', name='position', field=models.CharField(
            max_length=3, choices=[('S', 'Supporting'), ('O', 'Opposing'), ('M', 'Mentioned'),
                ('24F', 'Supporting communication'), ('24N', 'Opposing communication')])),
        migrations.RunPython(revision.install, revision.uninstall),
        migrations.RunPython(migrations.RunPython.noop, safe_reverse),
    ]
