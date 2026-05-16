"""Per-store content layer.

Spec 03 introduces a :class:`StoreRegistry` that resolves a
``(tenant_slug, store_slug)`` pair to a fully-wired bundle of
``FileSystem`` / ``GitBackend`` / ``TransactionManager``. The actual HTTP
routing that consults the registry lives in spec 04.
"""
