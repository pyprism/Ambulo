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
