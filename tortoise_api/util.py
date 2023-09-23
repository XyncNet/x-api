from datetime import date
from urllib.parse import parse_qsl, unquote

from asyncpg import Polygon, Range
from tortoise.fields import Field
from tortoise.fields.relational import RelationalField, ReverseRelation
from tortoise_api_model import Model


async def jsonify(obj: Model) -> dict:
    async def check(field: Field, key: str):
        async def rel_pack(mod: Model) -> dict:
            return {mod._meta.pk_attr: mod.pk, 'type': mod.__class__.__name__, 'repr': await mod.repr()}

        prop = getattr(obj, key)

        # if isinstance(prop, date):
        #     return prop.__str__().split('+')[0].split('.')[0] # '+' separates tz part, '.' separates millisecond part
        # if isinstance(prop, Polygon):
        #     return prop.points
        # if isinstance(prop, Range):
        #     return prop.lower, prop.upper
        if isinstance(field, RelationalField):
            if isinstance(prop, Model):
                return await rel_pack(prop)
            elif isinstance(prop, ReverseRelation) and isinstance(prop.related_objects, list):
                return [await rel_pack(d) for d in prop.related_objects]
            elif prop is None:
                return ''
            return None
        return getattr(obj, key)

    return {key: await check(field, key) for key, field in obj._meta.fields_map.items() if not key.endswith('_id')}

async def update(model: type[Model], dct: dict, oid):
    return await model.update_or_create(dct, **{model._meta.pk_attr: oid})
