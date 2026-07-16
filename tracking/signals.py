from django.db.models.signals import post_save
from django.dispatch import receiver

from utils.enums import SyncSource
from utils.tasks import safe_delay

from .models import LocationPoint, Place
from .tasks import process_geofence_events, reverse_geocode_place


@receiver(post_save, sender=LocationPoint)
def trigger_geofence_check(sender, instance, **kwargs):
    # Historical import points aren't live movement — running geofence
    # transitions against years-old rows corrupts Place.currently_inside
    # and spams friends with stale "entered/exited" notifications .
    if not instance.deleted_at and instance.source != SyncSource.import_:
        safe_delay(process_geofence_events, str(instance.pk))


@receiver(post_save, sender=Place)
def trigger_reverse_geocode(sender, instance, created, **kwargs):
    if created and not instance.address:
        safe_delay(reverse_geocode_place, str(instance.pk))
