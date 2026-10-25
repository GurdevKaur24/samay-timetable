"""Does a timetable still match the college's data? Only data that affects scheduling counts: renaming the college or a
department, or changing a department's head or ready status, doesn't make a timetable out of date."""

import hashlib
import json


def schedule_fingerprint(data: dict) -> str:
    relevant = {k: v for k, v in data.items() if k not in ("name", "place", "term", "kind")}
    relevant["departments"] = sorted(d["id"] for d in data.get("departments", []))
    relevant["teachers"] = [{k: v for k, v in t.items() if k != "email"} for t in data.get("teachers", [])]  # emails don't affect scheduling
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()
