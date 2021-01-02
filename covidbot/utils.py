from datetime import datetime, date
from typing import Optional


def serialize_datetime(obj: object) -> str:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))


def unserialize_datetime(datestring: str) -> Optional[datetime]:
    if datestring is None:
        return None
    return datetime.fromisoformat(datestring)
