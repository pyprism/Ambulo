import csv
import io
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from datetime import timezone as dt_timezone


def parse_ambulo_json(file_obj):
    data = json.load(file_obj)
    records = data if isinstance(data, list) else data.get("location_points", [])
    for row in records:
        if row.get("latitude") is None or row.get("longitude") is None:
            continue
        yield {
            "kind": "location_point",
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "recorded_at": row.get("recorded_at"),
            "altitude": row.get("altitude"),
        }


def parse_gpx(file_obj):
    tree = ET.parse(file_obj)
    root = tree.getroot()
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag not in ("trkpt", "wpt"):
            continue
        lat, lon = elem.get("lat"), elem.get("lon")
        if lat is None or lon is None:
            continue
        time_text, ele_text = None, None
        for child in elem:
            child_tag = child.tag.rsplit("}", 1)[-1]
            if child_tag == "time":
                time_text = child.text
            elif child_tag == "ele":
                ele_text = child.text
        try:
            yield {
                "kind": "location_point",
                "latitude": float(lat),
                "longitude": float(lon),
                "recorded_at": time_text or datetime.now(dt_timezone.utc).isoformat(),
                "altitude": float(ele_text) if ele_text else None,
            }
        except ValueError:
            continue


def parse_geojson(file_obj):
    data = json.load(file_obj)
    features = data.get("features", []) if isinstance(data, dict) else []
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        coords = geometry.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        if lat is None or lon is None:
            continue
        props = feature.get("properties") or {}
        yield {
            "kind": "location_point",
            "latitude": lat,
            "longitude": lon,
            "recorded_at": props.get("time")
            or props.get("recorded_at")
            or datetime.now(dt_timezone.utc).isoformat(),
            "altitude": props.get("altitude"),
        }


def parse_owntracks(file_obj):
    raw = file_obj.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    raw = raw.strip()
    if raw.startswith("["):
        rows = json.loads(raw)
    else:
        rows = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # OwnTracks .rec lines: "<iso ts>\t<topic>\t<json>"
            payload = line.split("\t")[-1]
            try:
                rows.append(json.loads(payload))
            except json.JSONDecodeError:
                continue
    for row in rows:
        if row.get("_type") != "location":
            continue
        tst = row.get("tst")
        recorded_at = (
            datetime.fromtimestamp(tst, tz=dt_timezone.utc).isoformat() if tst else None
        )
        vel_kmh = row.get("vel")
        # A malformed 'vel' (wrong type from a hand-edited/non-conforming
        # file) must not raise here — this runs eagerly per row, before the
        # yielded dict ever reaches _run_import's per-record try/except, so
        # an uncaught error kills the whole import job instead of just this
        # one row.
        if not isinstance(vel_kmh, (int, float)):
            vel_kmh = None
        yield {
            "kind": "location_point",
            "latitude": row.get("lat"),
            "longitude": row.get("lon"),
            "recorded_at": recorded_at,
            "altitude": row.get("alt"),
            "battery_level": row.get("batt"),
            "horizontal_accuracy": row.get("acc"),
            "vertical_accuracy": row.get("vac"),
            # OwnTracks 'vel' is km/h; Ambulo stores speed in m/s.
            "speed": vel_kmh * 1000 / 3600 if vel_kmh is not None else None,
            "heading": row.get("cog"),
        }


def parse_google_takeout(file_obj):
    data = json.load(file_obj)
    for row in data.get("locations", []):
        lat, lon = row.get("latitudeE7"), row.get("longitudeE7")
        if lat is None or lon is None:
            continue
        ts_ms = row.get("timestampMs") or row.get("timestamp")
        recorded_at = None
        if ts_ms:
            try:
                recorded_at = datetime.fromtimestamp(
                    int(ts_ms) / 1000, tz=dt_timezone.utc
                ).isoformat()
            except (TypeError, ValueError):
                recorded_at = str(ts_ms)
        yield {
            "kind": "location_point",
            "latitude": lat / 1e7,
            "longitude": lon / 1e7,
            "recorded_at": recorded_at,
            "altitude": row.get("altitude"),
        }


def parse_owntracks_csv(file_obj):
    """OwnTracks CSV export: time/tst, lat, lon, alt, batt columns."""
    raw = file_obj.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        lat, lon = row.get("lat"), row.get("lon")
        if not lat or not lon:
            continue
        tst = row.get("time") or row.get("tst")
        recorded_at = None
        if tst:
            try:
                recorded_at = datetime.fromtimestamp(
                    int(tst), tz=dt_timezone.utc
                ).isoformat()
            except (TypeError, ValueError):
                recorded_at = tst  # already an ISO string
        try:
            # A malformed 'vel' must skip only this row (caught below), not
            # raise before the try the way computing it outside this block
            # would.
            vel_kmh = float(row["vel"]) if row.get("vel") else None
            yield {
                "kind": "location_point",
                "latitude": float(lat),
                "longitude": float(lon),
                "recorded_at": recorded_at,
                "altitude": float(row["alt"]) if row.get("alt") else None,
                "battery_level": float(row["batt"]) if row.get("batt") else None,
                "horizontal_accuracy": float(row["acc"]) if row.get("acc") else None,
                "vertical_accuracy": float(row["vac"]) if row.get("vac") else None,
                # OwnTracks 'vel' is km/h; Ambulo stores speed in m/s.
                "speed": vel_kmh * 1000 / 3600 if vel_kmh is not None else None,
                "heading": float(row["cog"]) if row.get("cog") else None,
            }
        except ValueError:
            continue


def parse_google_takeout_semantic(file_obj):
    """Google Takeout "Semantic Location History" (newer format: a
    timelineObjects array of activitySegment/placeVisit, ISO timestamps —
    structurally different from the older locations.json array parsed by
    parse_google_takeout)."""
    data = json.load(file_obj)
    for obj in data.get("timelineObjects", []):
        activity = obj.get("activitySegment")
        if activity:
            duration = activity.get("duration", {})
            for loc_key, ts_key in (
                ("startLocation", "startTimestamp"),
                ("endLocation", "endTimestamp"),
            ):
                loc = activity.get(loc_key)
                recorded_at = duration.get(ts_key)
                if loc and loc.get("latitudeE7") is not None and recorded_at:
                    yield {
                        "kind": "location_point",
                        "latitude": loc["latitudeE7"] / 1e7,
                        "longitude": loc["longitudeE7"] / 1e7,
                        "recorded_at": recorded_at,
                        "altitude": None,
                    }
            continue

        visit = obj.get("placeVisit")
        if visit:
            loc = visit.get("location") or {}
            recorded_at = visit.get("duration", {}).get("startTimestamp")
            if loc.get("latitudeE7") is not None and recorded_at:
                yield {
                    "kind": "location_point",
                    "latitude": loc["latitudeE7"] / 1e7,
                    "longitude": loc["longitudeE7"] / 1e7,
                    "recorded_at": recorded_at,
                    "altitude": None,
                }


def parse_tcx(file_obj):
    """TCX (Training Center XML) workout export — Google Fit and Garmin
    both use it. Trackpoints carry position + optional heart rate; yields
    both record kinds."""
    tree = ET.parse(file_obj)
    root = tree.getroot()
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1] != "Trackpoint":
            continue
        time_text = lat = lon = alt = heart_rate = None
        for child in elem:
            child_tag = child.tag.rsplit("}", 1)[-1]
            if child_tag == "Time":
                time_text = child.text
            elif child_tag == "Position":
                for pos_child in child:
                    pos_tag = pos_child.tag.rsplit("}", 1)[-1]
                    if pos_tag == "LatitudeDegrees":
                        lat = pos_child.text
                    elif pos_tag == "LongitudeDegrees":
                        lon = pos_child.text
            elif child_tag == "AltitudeMeters":
                alt = child.text
            elif child_tag == "HeartRateBpm":
                for hr_child in child:
                    if hr_child.tag.rsplit("}", 1)[-1] == "Value":
                        heart_rate = hr_child.text

        if lat is not None and lon is not None and time_text:
            try:
                yield {
                    "kind": "location_point",
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "recorded_at": time_text,
                    "altitude": float(alt) if alt is not None else None,
                }
            except ValueError:
                continue
        if heart_rate is not None and time_text:
            try:
                yield {
                    "kind": "health_sample",
                    "metric_type": "heart_rate",
                    "value": float(heart_rate),
                    "recorded_at": time_text,
                }
            except ValueError:
                continue


PARSERS = {
    "ambulo_json": parse_ambulo_json,
    "gpx": parse_gpx,
    "geojson": parse_geojson,
    "owntracks": parse_owntracks,
    "owntracks_csv": parse_owntracks_csv,
    "google_takeout": parse_google_takeout,
    "google_takeout_semantic": parse_google_takeout_semantic,
    "tcx": parse_tcx,
}
