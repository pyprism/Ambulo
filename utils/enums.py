from django.db import models


class SyncState(models.TextChoices):
    local_only = "local_only", "Local Only"
    pending_upload = "pending_upload", "Pending Upload"
    synced = "synced", "Synced"
    conflict = "conflict", "Conflict"
    failed = "failed", "Failed"
    deleted_pending_sync = "deleted_pending_sync", "Deleted Pending Sync"


class SyncSource(models.TextChoices):
    manual = "manual", "Manual"
    location = "location", "Location"
    motion = "motion", "Motion"
    health = "health", "Health"
    import_ = "import", "Import"
    server = "server", "Server"


class MonitoringMode(models.TextChoices):
    quit = "quit", "Quit"
    manual = "manual", "Manual"
    significant = "significant", "Significant"
    move = "move", "Move"


class BiologicalSex(models.TextChoices):
    male = "male", "Male"
    female = "female", "Female"
    other = "other", "Other"


class DevicePlatform(models.TextChoices):
    android = "android", "Android"
    ios = "ios", "iOS"
    web = "web", "Web"
    other = "other", "Other"


class Connectivity(models.TextChoices):
    wifi = "wifi", "WiFi"
    cellular = "cellular", "Cellular"
    offline = "offline", "Offline"
    unknown = "unknown", "Unknown"


class HealthMetricType(models.TextChoices):
    steps = "steps", "Steps"
    distance = "distance", "Distance"
    active_minutes = "active_minutes", "Active Minutes"
    calories = "calories", "Calories"
    floors = "floors", "Floors"
    weight = "weight", "Weight"
    height = "height", "Height"
    water = "water", "Water"
    sleep = "sleep", "Sleep"
    mood = "mood", "Mood"
    heart_rate = "heart_rate", "Heart Rate"
    custom = "custom", "Custom"


class ActivityType(models.TextChoices):
    still = "still", "Still"
    walking = "walking", "Walking"
    running = "running", "Running"
    cycling = "cycling", "Cycling"
    vehicle = "vehicle", "Vehicle"
    unknown = "unknown", "Unknown"


class GoalPeriod(models.TextChoices):
    daily = "daily", "Daily"
    weekly = "weekly", "Weekly"
    monthly = "monthly", "Monthly"
    custom = "custom", "Custom"


class PlaceCategory(models.TextChoices):
    home = "home", "Home"
    work = "work", "Work"
    gym = "gym", "Gym"
    travel = "travel", "Travel"
    custom = "custom", "Custom"


class FriendshipStatus(models.TextChoices):
    pending = "pending", "Pending"
    accepted = "accepted", "Accepted"
    blocked = "blocked", "Blocked"


class NotificationType(models.TextChoices):
    friend_request = "friend_request", "Friend Request"
    friend_accept = "friend_accept", "Friend Accepted"
    friend_geofence = "friend_geofence", "Friend Geofence Event"


class ImportFormat(models.TextChoices):
    ambulo_json = "ambulo_json", "Ambulo JSON"
    gpx = "gpx", "GPX"
    geojson = "geojson", "GeoJSON"
    owntracks = "owntracks", "OwnTracks (.rec/JSON)"
    owntracks_csv = "owntracks_csv", "OwnTracks CSV"
    google_takeout = "google_takeout", "Google Takeout (locations.json)"
    google_takeout_semantic = (
        "google_takeout_semantic",
        "Google Takeout (Semantic Location History)",
    )
    google_fit = "google_fit", "Google Fit (steps CSV)"
    tcx = "tcx", "TCX (Google Fit/Garmin workout export)"


class ExportFormat(models.TextChoices):
    json = "json", "JSON"
    csv = "csv", "CSV"
    gpx = "gpx", "GPX"
    geojson = "geojson", "GeoJSON"


class JobStatus(models.TextChoices):
    pending = "pending", "Pending"
    processing = "processing", "Processing"
    preview_ready = "preview_ready", "Preview Ready"
    completed = "completed", "Completed"
    failed = "failed", "Failed"
    partial = "partial", "Partial"
