import time
import uuid
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from tracking.models import LocationPoint


class Command(BaseCommand):
    help = "Benchmark batch sync + pagination against a load_test_generate dataset."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="loadtest")
        parser.add_argument("--page-size", type=int, default=100)
        parser.add_argument("--pages", type=int, default=20)
        parser.add_argument("--upload-batch", type=int, default=500)

    def handle(self, *args, **options):
        if "testserver" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

        username = options["username"]
        user = User.objects.get(username=username)
        total_points = LocationPoint.objects.filter(user=user).count()
        self.stdout.write(f"Dataset size for '{username}': {total_points} points")

        client = APIClient()
        client.force_authenticate(user=user)

        # This tool measures raw endpoint throughput, not the auth rate
        # limiter (that's covered separately) — a tight benchmarking loop
        # would otherwise trip the per-minute throttle within seconds.
        with patch(
            "rest_framework.throttling.SimpleRateThrottle.allow_request",
            return_value=True,
        ):
            page_size = options["page_size"]
            pages = options["pages"]
            start = time.perf_counter()
            for i in range(pages):
                response = client.get(
                    f"/api/points/?page={i + 1}&page_size={page_size}"
                )
                assert response.status_code == 200, response.content
            elapsed = time.perf_counter() - start
            self.stdout.write(
                f"Pagination: {pages} pages x {page_size} rows in {elapsed:.3f}s "
                f"({elapsed / pages * 1000:.1f}ms/page avg)"
            )

            start = time.perf_counter()
            cursor = 0
            batches = 0
            fetched = 0
            while True:
                response = client.get(f"/api/sync/download/?location_point={cursor}")
                assert response.status_code == 200, response.content
                payload = response.data["location_point"]
                fetched += len(payload["records"])
                cursor = payload["cursor"]
                batches += 1
                if not payload["has_more"]:
                    break
            elapsed = time.perf_counter() - start
            self.stdout.write(
                f"Changed-since download: {fetched} records in {batches} batches, {elapsed:.3f}s "
                f"({elapsed / batches * 1000:.1f}ms/batch avg)"
            )

            batch = options["upload_batch"]
            payload = [
                {
                    "id": str(uuid.uuid4()),
                    "latitude": 1.0,
                    "longitude": 1.0,
                    "recorded_at": timezone.now().isoformat(),
                }
                for _ in range(batch)
            ]
            start = time.perf_counter()
            response = client.post("/api/points/", payload, format="json")
            elapsed = time.perf_counter() - start
            assert response.status_code in (200, 201), response.content
            accepted = len(response.data["accepted"])
            self.stdout.write(
                f"Batch upload: {accepted}/{batch} accepted in {elapsed:.3f}s "
                f"({batch / elapsed:.0f} points/sec)"
            )
