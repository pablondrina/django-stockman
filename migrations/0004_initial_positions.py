"""
Create initial Positions for the bakery.

Positions are places where stock exists (or doesn't exist, for virtual).
"""

from django.db import migrations


def create_initial_positions(apps, schema_editor):
    """Create the basic positions for a bakery."""
    Position = apps.get_model('stockman', 'Position')
    
    positions = [
        {
            'code': 'vitrine',
            'name': 'Vitrine',
            'kind': 'physical',
            'is_saleable': True,
            'is_default': True,
        },
        {
            'code': 'producao',
            'name': 'Área de Produção',
            'kind': 'physical',
            'is_saleable': False,
            'is_default': False,
        },
        {
            'code': 'deposito',
            'name': 'Depósito',
            'kind': 'physical',
            'is_saleable': False,
            'is_default': False,
        },
        {
            'code': 'perdas',
            'name': 'Perdas',
            'kind': 'virtual',
            'is_saleable': False,
            'is_default': False,
        },
    ]
    
    for pos_data in positions:
        Position.objects.get_or_create(
            code=pos_data['code'],
            defaults=pos_data
        )


def remove_initial_positions(apps, schema_editor):
    """Remove initial positions (for reverse migration)."""
    Position = apps.get_model('stockman', 'Position')
    Position.objects.filter(
        code__in=['vitrine', 'producao', 'deposito', 'perdas']
    ).delete()


class Migration(migrations.Migration):
    """Create initial positions for the bakery."""

    dependencies = [
        ('stockman', '0003_add_position_is_default'),
    ]

    operations = [
        migrations.RunPython(create_initial_positions, remove_initial_positions),
    ]






