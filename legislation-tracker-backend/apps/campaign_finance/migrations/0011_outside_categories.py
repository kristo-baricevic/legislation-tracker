from django.db import migrations, models
from importlib import import_module

revision = import_module('apps.campaign_finance.migrations.0010_outside_revision_triggers')


def safe_reverse(apps, editor):
    from django.db.migrations.exceptions import IrreversibleError
    if apps.get_model('campaign_finance', 'OutsideSpendingScan').objects.exclude(category='independent').exists():
        raise IrreversibleError('New spending categories contain saved scans; export/archive them before reverting.')


class Migration(migrations.Migration):
    dependencies = [('campaign_finance', '0010_outside_revision_triggers')]
    operations = [
        migrations.RunPython(revision.uninstall, revision.install),
        migrations.AddField(model_name='outsidespendingscan', name='category', field=models.CharField(
            max_length=20, default='independent', choices=[('independent', 'Independent expenditures'),
            ('communication', 'Communication costs'), ('electioneering', 'Electioneering communications')])),
        migrations.RemoveConstraint(model_name='outsidespendingscan', name='outside_scan_candidate_unique'),
        migrations.AddConstraint(model_name='outsidespendingscan', constraint=models.UniqueConstraint(
            fields=['snapshot', 'candidate_id', 'category'], name='outside_scan_category_unique')),
        migrations.AlterField(model_name='outsidespendingtotal', name='position', field=models.CharField(
            max_length=1, choices=[('S', 'Supporting'), ('O', 'Opposing'), ('M', 'Mentioned')])),
        migrations.RunPython(revision.install, revision.uninstall),
        migrations.RunPython(migrations.RunPython.noop, safe_reverse),
    ]
