import secrets

from django.db import migrations, models


def backfill_share_codes(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.filter(share_code=""):
        while True:
            code = secrets.token_hex(4)
            if not User.objects.filter(share_code=code).exists():
                break
        user.share_code = code
        user.save(update_fields=["share_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="share_code",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.RunPython(backfill_share_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="share_code",
            field=models.CharField(blank=True, max_length=16, unique=True),
        ),
    ]
