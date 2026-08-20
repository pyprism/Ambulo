from datetime import timedelta
from math import atan2, cos, radians, sin, sqrt

import requests
from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from utils.enums import SyncSource, SyncState

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
def process_geofence_events(user_id):
    """Sweep every one of a user's Place geofences against every point
    recorded since that place's `state_as_of`, resolving enter/exit
    transitions in chronological order.

    signals.py enqueues this at most once per 60s debounce window (one
    cache key per user) regardless of how many points were saved in that
    window — so the sweep, not the triggering point, is what has to see
    every point. A version keyed on a single remembered point id examines
    only that one point per window: a batched upload's mid-batch
    enter/exit transitions are silently skipped, `last_entered_at`/
    `last_exited_at` land on the wrong point, and short visits vanish.

    Points arrive out of order across concurrent Celery tasks (batch sync,
    retries) — a `select_for_update` per place plus the `state_as_of`
    staleness guard makes sure only points strictly after the last
    processed one can move `currently_inside`, and processing them in
    `recorded_at` order keeps transitions chronological even when this
    sweep and another run's sweep race.
    """
    pending_key = f"geofence-sweep-pending:{user_id}"
    try:
        for place_id in (
            Place.objects.filter(user_id=user_id)
            .not_deleted()
            .values_list("pk", flat=True)
        ):
            transitions = []
            with transaction.atomic():
                place = Place.objects.select_for_update().get(pk=place_id)
                points = (
                    LocationPoint.objects.filter(user_id=user_id)
                    .not_deleted()
                    .exclude(source=SyncSource.import_)
                    .order_by("recorded_at")
                )
                if place.state_as_of is not None:
                    points = points.filter(recorded_at__gt=place.state_as_of)
                else:
                    # A place with no processed state yet (just created) has
                    # no natural lower bound — without one this replays every
                    # point the user has ever synced (100k+ in the load-tested
                    # case) inside a select_for_update on the place, and fires
                    # one friend notification per historical transition.
                    # Seed from the single most recent point instead: that
                    # establishes an initial currently_inside/state_as_of
                    # without walking history.
                    latest_id = (
                        points.order_by("-recorded_at")
                        .values_list("pk", flat=True)
                        .first()
                    )
                    points = points.filter(pk=latest_id) if latest_id else points.none()

                changed = False
                for point in points.iterator(chunk_size=500):
                    distance = _haversine_meters(
                        point.latitude,
                        point.longitude,
                        place.latitude,
                        place.longitude,
                    )
                    is_inside = distance <= place.radius_meters
                    place.state_as_of = point.recorded_at
                    changed = True
                    if is_inside and not place.currently_inside:
                        place.currently_inside = True
                        place.last_entered_at = point.recorded_at
                        transitions.append("entered")
                    elif not is_inside and place.currently_inside:
                        place.currently_inside = False
                        place.last_exited_at = point.recorded_at
                        transitions.append("exited")
                if changed:
                    place.save()

            if place.notify_friends:
                for transitioned in transitions:
                    _notify_friends(user_id, place.name, transitioned)
    finally:
        cache.delete(pending_key)


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
        for point in stale.iterator(chunk_size=500):
            point.deleted_at = now
            point.sync_state = SyncState.deleted_pending_sync
            point.save()
            total += 1
    return total
