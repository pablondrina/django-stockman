# Generated manually — removes dead constraint unique_quant_coordinate_no_batch.
# The condition Q(batch__isnull=True) never fires because batch is CharField(default='').

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stockman', '0008_add_batch_model'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='quant',
            name='unique_quant_coordinate_no_batch',
        ),
    ]
