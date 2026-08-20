import uuid
from datetime import date

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from health.models import DailyRollup, HealthSample
from utils.enums import HealthMetricType


@pytest.fixture
def user(db):
    return User.objects.create_registered_user(
        username="health-user",
        email="health-user@example.com",
        password="testpass12345",
    )


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_stats_summary_only_includes_authenticated_users_rollups(api_client, user):
    other_user = User.objects.create_registered_user(
        username="other-health-user",
        email="other-health-user@example.com",
        password="testpass12345",
    )
    DailyRollup.objects.create(user=user, date=date.today(), steps=1000, floors=2)
    DailyRollup.objects.create(
        user=other_user, date=date.today(), steps=9000, floors=99
    )

    response = api_client.get("/api/stats/summary/?period=today")

    assert response.status_code == 200
    assert response.data["steps"] == 1000
    assert response.data["floors"] == 2


@pytest.mark.django_db
def test_stats_trend_averages_point_in_time_health_samples(api_client, user):
    HealthSample.objects.create(
        id=uuid.uuid4(),
        user=user,
        metric_type=HealthMetricType.weight,
        value=70,
        unit="kg",
        recorded_at=timezone.now(),
    )
    HealthSample.objects.create(
        id=uuid.uuid4(),
        user=user,
        metric_type=HealthMetricType.weight,
        value=72,
        unit="kg",
        recorded_at=timezone.now(),
    )

    response = api_client.get(
        f"/api/stats/trend/?metric={HealthMetricType.weight}"
        f"&start={date.today().isoformat()}&end={date.today().isoformat()}"
    )

    assert response.status_code == 200
    assert response.data["metric"] == HealthMetricType.weight
    assert response.data["points"] == [{"date": date.today(), "value": 71.0}]


@pytest.mark.django_db
def test_daily_rollup_maxes_multi_device_sensor_samples_but_sums_manual_ones(
    user,
):
    from accounts.models import Device
    from health.tasks import compute_daily_rollup
    from utils.enums import SyncSource

    device_a = Device.objects.create(user=user, name="A", platform="android")
    device_b = Device.objects.create(user=user, name="B", platform="ios")
    day = timezone.now()

    # Two devices reporting the same underlying activity — collapsed to the
    # higher device total, not summed to ~2x.
    HealthSample.objects.create(
        id=uuid.uuid4(),
        user=user,
        device=device_a,
        metric_type=HealthMetricType.calories,
        value=500,
        recorded_at=day,
        source=SyncSource.motion,
    )
    HealthSample.objects.create(
        id=uuid.uuid4(),
        user=user,
        device=device_b,
        metric_type=HealthMetricType.calories,
        value=600,
        recorded_at=day,
        source=SyncSource.motion,
    )
    # Two separately-logged manual entries — no per-device dedup guarantee,
    # so these must sum instead of the larger silently replacing the other.
    HealthSample.objects.create(
        id=uuid.uuid4(),
        user=user,
        metric_type=HealthMetricType.calories,
        value=300,
        recorded_at=day,
        source=SyncSource.manual,
    )
    HealthSample.objects.create(
        id=uuid.uuid4(),
        user=user,
        metric_type=HealthMetricType.calories,
        value=200,
        recorded_at=day,
        source=SyncSource.manual,
    )

    compute_daily_rollup(user.pk, day.date().isoformat())

    rollup = DailyRollup.objects.get(user=user, date=day.date())
    assert rollup.calories == 600 + 300 + 200
