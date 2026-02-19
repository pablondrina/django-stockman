# Changelog — Django Stockman

## [0.1.3] - 2025-01-XX

### Fixed

**Disponibilidade não depende mais do cron para ser correta.**

Antes, se o cron atrasasse, holds expirados ainda bloqueavam estoque:

```
00:15 - Hold expira
00:16 - Cliente B tenta comprar → BLOQUEADO (hold ainda "ativo")
00:20 - Cron roda, libera hold → agora disponível
```

Agora, a disponibilidade é sempre correta em tempo real:

```
00:15 - Hold expira
00:16 - Cliente B tenta comprar → DISPONÍVEL (hold ignorado)
00:20 - Cron roda → apenas limpa registro (sem impacto no negócio)
```

### Changed

- `stock.available()` — ignora holds expirados na consulta
- `stock.demand()` — ignora holds expirados na consulta
- `Quant.held` property — ignora holds expirados na soma
- `Hold.is_active` property — retorna `False` se expirado
- **PositionKind simplificado** — de 4 tipos para 2:
  - Removidos: `LOGICAL`, `PROCESS` (redundantes com PHYSICAL)
  - Mantidos: `PHYSICAL` (produto existe em lugar real), `VIRTUAL` (registro contábil)
  - Migration automática converte LOGICAL/PROCESS → PHYSICAL

### Technical Details

Todas as consultas de holds ativos agora incluem filtro de expiração:

```python
Hold.objects.filter(
    status__in=[HoldStatus.PENDING, HoldStatus.CONFIRMED]
).filter(
    Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
)
```

O cron (`release_expired_holds`) continua sendo necessário para:
- Limpar registros (mudar status para RELEASED)
- Manter o banco organizado

Mas a **lógica de negócio não depende do cron**.

### Tests Added

- `test_available_ignores_expired_holds_before_cron`
- `test_hold_is_active_false_when_expired`
- `test_quant_held_ignores_expired_holds`
- `test_new_hold_succeeds_when_old_expired`

---

## [0.1.0] - 2025-01-XX

### Initial Release

- Modelos: Position, Quant, Move, Hold
- API de serviço: stock.available, stock.hold, stock.confirm, stock.fulfill, stock.release
- Suporte a shelflife (validade de produtos)
- Suporte a demand (holds sem estoque vinculado)
- Integração com Django Salesman via modifiers

