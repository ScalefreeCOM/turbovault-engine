# TurboVault Engine - Model Standards

## Timestamp Fields

All models in the TurboVault Engine **MUST** include `created_at` and `updated_at` timestamp fields for audit tracking.

### Standard Implementation

```python
created_at = models.DateTimeField(
    auto_now_add=True,
    help_text="Timestamp when the [model] was created"
)

updated_at = models.DateTimeField(
    auto_now=True,
    help_text="Timestamp when the [model] was last updated"
)
```

### Current Status

✅ **Project** - Has timestamps  
✅ **SourceSystem** - Has timestamps (added in migration 0002)  
✅ **SourceTable** - Has timestamps (added in migration 0002)  
✅ **SourceColumn** - Has timestamps (added in migration 0002)

### Future Models

All future domain models (Hubs, Links, Satellites, etc.) MUST include these timestamp fields from the initial creation.
