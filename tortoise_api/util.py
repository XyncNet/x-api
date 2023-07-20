from datetime import date
from tortoise.fields import Field
from tortoise.fields.relational import RelationalField, ReverseRelation
from tortoise_api_model import Model

def jsonify(obj: Model) -> dict:
    def check(field: Field, key: str):
        prop = getattr(obj, key)
        if isinstance(prop, date):
            return prop.__str__().split('.')[0].split('+')[0]
        elif isinstance(field, RelationalField):
            if isinstance(prop, Model):
                return rel_pack(prop)
            elif isinstance(prop, ReverseRelation) and isinstance(prop.related_objects, list):
                return [rel_pack(d) for d in prop.related_objects]
            else:
                return '[X]'
        else:
            return getattr(obj, key)

    return {key: check(field, key) for key, field in obj._meta.fields_map.items() if not key.endswith('_id')}

def rel_pack(mod: Model) -> dict:
    return {'id': mod.id, 'type': mod.__class__.__name__, 'repr': mod.repr()}
