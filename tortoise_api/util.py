from datetime import date
from urllib.parse import parse_qsl, unquote

from asyncpg import Polygon, Range
from tortoise.fields import Field
from tortoise.fields.relational import RelationalField, ReverseRelation, ManyToManyRelation
from tortoise.models import MetaInfo
from tortoise.queryset import QuerySet
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
        if k.endswith('[]'):
            k = k[:-2]
            # for list-like fields(2d lists: (1d list of 1d tuples)): '.'-separated param names splits to {key}.{index}
            if '.' in k:
                k, i = k.split('.')
                i = int(i)
                data[k] = data.get(k, [()])
                if len(data[k]) > i:
                    data[k][i] += (v,)
                else:
                    data[k].append((v,))
            else:
                data[k] = data.get(k, ()) + (v,)
        # todo: make list with no collections ablility
        # elif '.' in k:
        #     k, i = k.split('.')
        #     i = int(i)
        #     data[k] = data.get(k, [()])
        #     if len(data[k]) > i:
        #         data[k][i] += (v,)
        #     else:
        #         data[k].append((v,))

        else: # if v is IntEnum - it requires explicit convert to int
            data[k] = int(v) if v.isnumeric() else v
    return data

async def upsert(model: type[Model], data: dict):
    meta: MetaInfo = model._meta

    # pop fields for relations from general data dict
    m2ms = {k: data.pop(k) for k in model._meta.m2m_fields if k in data}
    bfks = {k: data.pop(k) for k in model._meta.backward_fk_fields if k in data}
    bo2os = {k: data.pop(k) for k in model._meta.backward_o2o_fields if k in data}

    # save general model
    if pk := meta.pk_attr in data.keys():
        unq = {pk: data.pop(pk)}
    else:
        unq = {key: data.pop(key) for key, ft in meta.fields_map.items() if ft.unique and key in data.keys()}
    # unq = meta.unique_together
    obj, is_created = await model.update_or_create(data, **unq)

    # save relations
    for k, ids in m2ms.items():
        m2m_rel: ManyToManyRelation = getattr(obj, k)
        items = [await m2m_rel.remote_model[i] for i in ids]
        await m2m_rel.add(*items)
    for k, ids in bfks.items():
        bfk_rel: ReverseRelation = getattr(obj, k)
        items = [await bfk_rel.remote_model[i] for i in ids]
        [await item.update_from_dict({bfk_rel.relation_field: obj.pk}).save() for item in items]
    for k, oid in bo2os.items():
        bo2o_rel: QuerySet = getattr(obj, k)
        item = await bo2o_rel.model[oid]
        await item.update_from_dict({obj._meta.db_table: obj}).save()

    return obj

async def update(model: type[Model], dct: dict, oid):
    return await model.update_or_create(dct, **{model._meta.pk_attr: oid})

async def delete(model: type[Model], oid):
    return await (await model[oid]).delete()
