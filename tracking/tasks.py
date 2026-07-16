from datetime import timedelta
from math import atan2, cos, radians, sin, sqrt

import requests
from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from utils.enums import SyncState

from .models import LocationPoint, Place

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
GEOCODE_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days
GEOCODE_CACHE_PRECISION = 4  # ~11m grid — keeps cache hit rate high nearby


def _geocode_cache_key(lat, lon):
    return f"reverse_geocode:{round(lat, GEOCODE_CACHE_PRECISION)}:{round(lon, GEOCODE_CACHE_PRECISION)}"


@shared_task(name="tracking.reverse_geocode_place", bind=True, max_retries=3)
def reverse_geocode_place(self, place_id):
    try:
        place = Place.objects.get(pk=place_id)
    except Place.DoesNotExist:
        return None

    key = _geocode_cache_key(place.latitude, place.longitude)
    address = cache.get(key)
    if address is None:
        try:
            response = requests.get(
                NOMINATIM_URL,
                params={
                    "lat": place.latitude,
                    "lon": place.longitude,
                    "format": "json",
                },
                headers={"User-Agent": "Ambulo/1.0"},
                timeout=10,
            )
            response.raise_for_status()
            address = response.json().get("display_name", "")
        except requests.RequestException as exc:
            raise self.retry(exc=exc, countdown=30)
        cache.set(key, address, GEOCODE_CACHE_TTL)

    place.address = address
    place.save(update_fields=["address"])
    return address


def _haversine_meters(lat1, lon1, lat2, lon2):
    earth_radius = 6371000
    p1, p2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)
    a = sin(d_phi / 2) ** 2 + cos(p1) * cos(p2) * sin(d_lambda / 2) ** 2
    return 2 * earth_radius * atan2(sqrt(a), sqrt(1 - a))


@shared_task(name="tracking.process_geofence_events")
def process_geofence_events(location_point_id):
    """Update each of the point's user's Place geofences with enter/exit
    transitions.

    Points arrive out of order across concurrent Celery tasks (batch sync,
    retries) — a `select_for_update` per place plus the `state_as_of`
    staleness guard makes sure only the chronologically latest point
    processed so far can move `currently_inside`.
    """
    try:
        point = LocationPoint.objects.get(pk=location_point_id)
    except LocationPoint.DoesNotExist:
        return

    for place_id in (
        Place.objects.for_user(point.user).not_deleted().values_list("pk", flat=True)
    ):
        with transaction.atomic():
            place = Place.objects.select_for_update().get(pk=place_id)
            if place.state_as_of is not None and point.recorded_at <= place.state_as_of:
                continue

            distance = _haversine_meters(
                point.latitude, point.longitude, place.latitude, place.longitude
            )
            is_inside = distance <= place.radius_meters
            place.state_as_of = point.recorded_at
            transitioned = None
            if is_inside and not place.currently_inside:
                place.currently_inside = True
                place.last_entered_at = point.recorded_at
                transitioned = "entered"
            elif not is_inside and place.currently_inside:
                place.currently_inside = False
                place.last_exited_at = point.recorded_at
                transitioned = "exited"
            place.save()

        if transitioned:
            _notify_friends(point.user_id, place.name, transitioned)


def _notify_friends(user_id, place_name, event_type):
    from social.tasks import notify_friend_geofence_event
    from utils.tasks import safe_delay

    safe_delay(notify_friend_geofence_event, str(user_id), place_name, event_type)


@shared_task(name="tracking.retention_cleanup")
def retention_cleanup():
    """Tombstone LocationPoints past each user's configured retention
    window . Soft-delete, not a hard
    DELETE, so the removal still propagates to other devices via the
    normal changed-since tombstone sync path."""
    from accounts.models import User

    now = timezone.now()
    total = 0
    for user in User.objects.exclude(location_retention_days__isnull=True):
        cutoff = now - timedelta(days=user.location_retention_days)
        stale = (
            LocationPoint.objects.for_user(user)
            .not_deleted()
            .filter(recorded_at__lt=cutoff)
        )
        count = stale.count()
        for point in stale:
            point.deleted_at = now
            point.sync_state = SyncState.deleted_pending_sync
            point.save()
        total += count
    return total
