"""Registry of syncable record types for the generic /sync/upload & /sync/download
surface. Each app that defines a SyncableModel registers it once (in its
AppConfig.ready()) so new record types plug into the shared sync spine
without touching sync/views.py.
"""

_registry = {}


def register_syncable(type_name, model, serializer_class):
    _registry[type_name] = (model, serializer_class)


def get_syncable(type_name):
    return _registry.get(type_name)


def all_syncable_types():
    return list(_registry.keys())
