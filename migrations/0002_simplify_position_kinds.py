"""
Simplify PositionKind enum: remove LOGICAL and PROCESS, keep only PHYSICAL and VIRTUAL.

LOGICAL and PROCESS were redundant with PHYSICAL - they all represent places
where the product physically exists. The only meaningful distinction is:
- PHYSICAL: Product exists in a real place
- VIRTUAL: Accounting concept (losses, adjustments)
"""

from django.db import migrations, models


def convert_to_physical(apps, schema_editor):
    """Convert LOGICAL and PROCESS positions to PHYSICAL."""
    Position = apps.get_model('stockman', 'Position')
    # Convert all non-PHYSICAL, non-VIRTUAL to PHYSICAL
    Position.objects.filter(kind__in=['logical', 'process']).update(kind='physical')


def reverse_migration(apps, schema_editor):
    """No reverse needed - data is preserved as PHYSICAL."""
    pass


class Migration(migrations.Migration):
    """Simplify PositionKind to PHYSICAL and VIRTUAL only."""

    dependencies = [
        ('stockman', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(convert_to_physical, reverse_migration),
        migrations.AlterField(
            model_name='position',
            name='kind',
            field=models.CharField(
                choices=[('physical', 'Físico'), ('virtual', 'Virtual')],
                default='physical',
                max_length=20,
                verbose_name='Tipo',
            ),
        ),
    ]

