import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from sync.models import RevisionCounter
from tracking.models import LocationPoint


class Command(BaseCommand):
    help = "Generate a multi-year synthetic LocationPoint dataset for load testing (plan.md Phase 5)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="loadtest")
        parser.add_argument("--years", type=int, default=3)
        parser.add_argument("--interval-minutes", type=int, default=15)
        parser.add_argument("--batch-size", type=int, default=5000)

    def handle(self, *args, **options):
        username = options["username"]
        years = options["years"]
        interval = options["interval_minutes"]
        batch_size = options["batch_size"]

        user, created = User.objects.get_or_create(
            username=username, defaults={"email": f"{username}@example.com"}
        )
        if created:
            user.set_unusable_password()
            user.save()

        end = timezone.now()
        start = end - timedelta(days=365 * years)
        total_points = int((end - start).total_seconds() // (interval * 60))
        self.stdout.write(
            f"Generating ~{total_points} points for '{username}' over {years} years "
            f"(one every {interval}min)..."
        )

        model_label = LocationPoint._meta.label
        with transaction.atomic():
            counter, _ = RevisionCounter.objects.select_for_update().get_or_create(
                model_label=model_label
            )
            rev = counter.value

        created_count = 0
        buffer = []
        current = start
        while current <= end:
            rev += 1
            buffer.append(
                LocationPoint(
                    id=uuid.uuid4(),
                    user=user,
                    latitude=23.8 + (created_count % 1000) * 0.0001,
                    longitude=90.4 + (created_count % 1000) * 0.0001,
                    recorded_at=current,
                    server_rev=rev,
                    source="import",
                )
            )
            created_count += 1
            current += timedelta(minutes=interval)
            if len(buffer) >= batch_size:
                LocationPoint.objects.bulk_create(buffer, batch_size=batch_size)
                buffer = []
                self.stdout.write(f"  ...{created_count}/{total_points}")

        if buffer:
            LocationPoint.objects.bulk_create(buffer, batch_size=batch_size)

        # bulk_create bypasses SyncableModel.save(), so the shared counter
        # never saw these — reconcile it once so future normal saves on
        # this model keep handing out fresh, non-colliding server_rev values.
        RevisionCounter.objects.filter(model_label=model_label).update(value=rev)

        self.stdout.write(
            self.style.SUCCESS(f"Created {created_count} points for '{username}'.")
        )
