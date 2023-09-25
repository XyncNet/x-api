from datetime import date
from urllib.parse import parse_qsl, unquote

from asyncpg import Polygon, Range
from tortoise.fields import Field
from tortoise.fields.relational import RelationalField, ReverseRelation
from tortoise_api_model import Model

async def with_rels(obj: Model) -> dict:
    async def check(field: Field, key: str):
        prop = getattr(obj, key)

        # if isinstance(prop, date):
        #     return prop.__str__().split('+')[0].split('.')[0] # '+' separates tz part, '.' separates millisecond part
        # if isinstance(prop, Polygon):
        #     return prop.points
        # if isinstance(prop, Range):
        #     return prop.lower, prop.upper
        if isinstance(field, RelationalField):
            if isinstance(prop, Model):
                return await _rel_pack(prop)
            elif isinstance(prop, ReverseRelation) and isinstance(prop.related_objects, list):
                return [await _rel_pack(d) for d in prop.related_objects]
            elif prop is None:
                return ''
            return None
        return getattr(obj, key)

    return {key: await check(field, key) for key, field in obj._meta.fields_map.items() if not key.endswith('_id')}

async def _rel_pack(rel_obj: Model) -> dict:
    return {'id': rel_obj.id, 'type': rel_obj.__class__.__name__, 'repr': await rel_obj.repr()}

