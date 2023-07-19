from datetime import date
from tortoise import Model
from tortoise.fields.relational import RelationalField, ReverseRelation


def _api_repr(obj: Model) -> dict:
    data = {}
    for key, field in obj._meta.fields_map.items():
        data[key] = getattr(obj, key)
        if isinstance(data[key], date):
            data[key] = data[key].__str__().split('.')[0].split('+')[0]
        elif isinstance(field, RelationalField):
            if isinstance(data[key], ReverseRelation) and isinstance(data[key].related_objects, list):
                data[key] = [d.repr() for d in data[key]]
            elif data[key]:
                data[key] = data[key].repr()
    return data
