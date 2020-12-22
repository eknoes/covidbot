from datetime import datetime, date


def serialize_datetime(obj: object) -> str:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))


def unserialize_datetime(datestring: str) -> datetime:
    return datetime.fromisoformat(datestring)
