"""
Initial migration for Stockman models.
"""

from decimal import Decimal
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Create Stockman models: Position, Quant, Move, Hold."""

    initial = True

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Position',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(help_text='Identificador único (ex: vitrine, deposito)', unique=True, verbose_name='Código')),
                ('name', models.CharField(help_text='Nome legível da posição', max_length=100, verbose_name='Nome')),
                ('kind', models.CharField(choices=[('physical', 'Físico'), ('logical', 'Lógico'), ('process', 'Processo'), ('virtual', 'Virtual')], default='physical', max_length=20, verbose_name='Tipo')),
                ('is_saleable', models.BooleanField(default=False, help_text='Se True, estoque aqui pode ser vendido diretamente.', verbose_name='Permite venda')),
                ('metadata', models.JSONField(blank=True, default=dict, verbose_name='Metadados')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Posição',
                'verbose_name_plural': 'Posições',
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='Quant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.PositiveIntegerField(verbose_name='ID do Produto')),
                ('target_date', models.DateField(blank=True, db_index=True, help_text='Vazio = estoque físico. Data = produção planejada.', null=True, verbose_name='Data Alvo')),
                ('batch', models.CharField(blank=True, default='', max_length=50, verbose_name='Lote')),
                ('_quantity', models.DecimalField(decimal_places=3, default=Decimal('0'), max_digits=12, verbose_name='Quantidade')),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='contenttypes.contenttype', verbose_name='Tipo de Produto')),
                ('position', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='quants', to='stockman.position', verbose_name='Posição')),
            ],
            options={
                'verbose_name': 'Quantidade',
                'verbose_name_plural': 'Quantidades',
            },
        ),
        migrations.CreateModel(
            name='Move',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('delta', models.DecimalField(decimal_places=3, help_text='Positivo = entrada, Negativo = saída', max_digits=12, verbose_name='Variação')),
                ('reference_id', models.PositiveIntegerField(blank=True, null=True)),
                ('reason', models.CharField(help_text='Obrigatório. Ex: "Produção manhã", "Venda #123"', max_length=255, verbose_name='Motivo')),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('timestamp', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('quant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='moves', to='stockman.quant', verbose_name='Quantidade')),
                ('reference_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='contenttypes.contenttype')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Usuário')),
            ],
            options={
                'verbose_name': 'Movimento',
                'verbose_name_plural': 'Movimentos',
                'ordering': ['timestamp'],
            },
        ),
        migrations.CreateModel(
            name='Hold',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.PositiveIntegerField()),
                ('quantity', models.DecimalField(decimal_places=3, max_digits=12, verbose_name='Quantidade')),
                ('target_date', models.DateField(db_index=True, verbose_name='Data Desejada')),
                ('status', models.CharField(choices=[('pending', 'Pendente'), ('confirmed', 'Confirmado'), ('fulfilled', 'Concluído'), ('released', 'Liberado')], db_index=True, default='pending', max_length=20, verbose_name='Status')),
                ('purpose_id', models.PositiveIntegerField(blank=True, null=True)),
                ('expires_at', models.DateTimeField(blank=True, db_index=True, help_text='Se não concluído até esta data, será liberado automaticamente', null=True, verbose_name='Expira em')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('resolved_at', models.DateTimeField(blank=True, help_text='Data de fulfillment ou release', null=True, verbose_name='Resolvido em')),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='contenttypes.contenttype')),
                ('purpose_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='contenttypes.contenttype')),
                ('quant', models.ForeignKey(blank=True, help_text='Vazio = demanda (cliente quer, mas não há estoque)', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='holds', to='stockman.quant', verbose_name='Estoque Vinculado')),
            ],
            options={
                'verbose_name': 'Bloqueio',
                'verbose_name_plural': 'Bloqueios',
            },
        ),
        # Indexes
        migrations.AddIndex(
            model_name='quant',
            index=models.Index(fields=['content_type', 'object_id'], name='stockman_qu_content_09d8a3_idx'),
        ),
        migrations.AddIndex(
            model_name='quant',
            index=models.Index(fields=['target_date'], name='stockman_qu_target__4e259e_idx'),
        ),
        migrations.AddIndex(
            model_name='quant',
            index=models.Index(fields=['position', 'target_date'], name='stockman_qu_positio_73cc97_idx'),
        ),
        migrations.AddConstraint(
            model_name='quant',
            constraint=models.UniqueConstraint(fields=('content_type', 'object_id', 'position', 'target_date', 'batch'), name='unique_quant_coordinate'),
        ),
        migrations.AddIndex(
            model_name='move',
            index=models.Index(fields=['quant', 'timestamp'], name='stockman_mo_quant_i_01d0c9_idx'),
        ),
        migrations.AddIndex(
            model_name='move',
            index=models.Index(fields=['timestamp'], name='stockman_mo_timesta_2d4ce4_idx'),
        ),
        migrations.AddIndex(
            model_name='hold',
            index=models.Index(fields=['status', 'expires_at'], name='stockman_ho_status_aaa8ec_idx'),
        ),
        migrations.AddIndex(
            model_name='hold',
            index=models.Index(fields=['content_type', 'object_id', 'target_date'], name='stockman_ho_content_8d3e50_idx'),
        ),
        migrations.AddIndex(
            model_name='hold',
            index=models.Index(fields=['status', 'quant'], name='stockman_ho_status_f7b3b2_idx'),
        ),
    ]







