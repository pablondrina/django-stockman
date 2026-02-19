"""
Position model — Where stock exists.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from stockman.models.enums import PositionKind


class Position(models.Model):
    """
    Where stock exists — physical, logical, or process stage.
    
    Positions are stable entities, created during system setup.
    
    For MVP, we use a flat structure (no hierarchy).
    django-treebeard can be added later if needed.
    
    Examples:
        Position.objects.create(code='vitrine', name='Vitrine', kind=PositionKind.PHYSICAL, is_saleable=True)
        Position.objects.create(code='producao', name='Produção', kind=PositionKind.PROCESS)
    """
    
    code = models.SlugField(
        unique=True,
        max_length=50,
        verbose_name=_('Código'),
        help_text=_('Identificador único (ex: vitrine, deposito)'),
    )
    name = models.CharField(
        max_length=100,
        verbose_name=_('Nome'),
        help_text=_('Nome legível da posição'),
    )
    kind = models.CharField(
        max_length=20,
        choices=PositionKind.choices,
        default=PositionKind.PHYSICAL,
        verbose_name=_('Tipo'),
    )
    is_saleable = models.BooleanField(
        default=False,
        verbose_name=_('Permite venda'),
        help_text=_('Se True, estoque aqui pode ser vendido diretamente.'),
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name=_('Posição padrão'),
        help_text=_('Se True, esta é a posição padrão para novos Quants.'),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_('Metadados'),
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Posição')
        verbose_name_plural = _('Posições')
        ordering = ['code']
    
    def __str__(self) -> str:
        return self.name


