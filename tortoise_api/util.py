from datetime import date
from urllib.parse import parse_qsl, unquote

from asyncpg import Polygon, Range
from tortoise.fields import Field
from tortoise.fields.relational import RelationalField, ReverseRelation
from tortoise_api_model import Model


def jsonify(obj: Model) -> dict:
    def check(field: Field, key: str):
        def rel_pack(mod: Model) -> dict:
            return {'id': mod.id, 'type': mod.__class__.__name__, 'repr': mod.repr()}

        prop = getattr(obj, key)
        if isinstance(prop, date):
            return prop.__str__().split('+')[0].split('.')[0] # '+' separates tz part, '.' separates millisecond part
        if isinstance(prop, Polygon):
            return prop.points
        if isinstance(prop, Range):
            return prop.lower, prop.upper
        elif isinstance(field, RelationalField):
            if isinstance(prop, Model):
                return rel_pack(prop)
            elif isinstance(prop, ReverseRelation) and isinstance(prop.related_objects, list):
                return [rel_pack(d) for d in prop.related_objects]
            elif prop is None:
                return ''
            return None
        else:
            return getattr(obj, key)

    return {key: check(field, key) for key, field in obj._meta.fields_map.items() if not key.endswith('_id')}

def parse_qs(s: str) -> dict:
    data = {}
    for k, v in parse_qsl(unquote(s)):
        # for collection-like fields (1d tuples): multiple the same name params merges to tuple
        if k in data:
            if isinstance(data[k], tuple):
                data[k] += (v,)
            else:
                data[k] = data[k], float(v)
        # for list-like fields(2d lists: (1d list of 1d tuples)): '.'-separated param names splits to {key}.{index}
        elif '.' in k:
            bk, i = k.split('.')
            i = int(i)
            data[bk] = data.get(bk, [()])
            if len(data[bk]) > i:
                data[bk][i] += (v,)
            else:
                data[bk].append((v,))
        else: # if v is IntEnum - it requires explicit convert to int
            data[k] = int(v) if v.isnumeric() else v
    return data

# async def upsert(model: type[Model], dct: dict):
#     meta: MetaInfo = model._meta
#     if pk := meta.pk_attr in dct.keys():
#         unq = {pk: dct.pop(pk)}
#     else:
#         unq = {key: dct.pop(key) for key, ft in meta.fields_map.items() if ft.unique and key in dct.keys()}
#     # unq = meta.unique_together
#     res = await model.update_or_create(dct, **unq)
#     return res

async def update(model: type[Model], dct: dict, oid):
    return await model.update_or_create(dct, **{model._meta.pk_attr: oid})

async def delete(model: type[Model], oid):
    return await (await model[oid]).delete()
