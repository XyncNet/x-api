import logging
from os import getenv as env
from types import ModuleType
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Path, HTTPException, Form
from fastapi.routing import APIRoute, APIRouter
# from fastapi_cache import FastAPICache
# from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette import status
from starlette.requests import Request
from tortoise import Tortoise
from tortoise.contrib.pydantic import pydantic_model_creator, PydanticModel
from tortoise.contrib.pydantic.creator import PydanticMeta
from tortoise.contrib.starlette import register_tortoise
from tortoise.exceptions import IntegrityError, DoesNotExist
from tortoise.queryset import QuerySet
from tortoise.signals import pre_save

from tortoise_api_model import Model, User
from tortoise_api_model.model import hash_pwd
from tortoise_api import oauth
from tortoise_api.oauth import login_for_access_token, Token, get_current_user, reg_user


class Api:
    app: FastAPI
    models: {str: Model}
    redis = None
    prefix = '/v2'

    def __init__(
        self,
        models_module: ModuleType,
        debug: bool = False,
        title: str = 'FemtoAPI',
        exc_models: [str] = [],
    ):
        """
        Parameters:
            debug: Debug SQL queries, api requests
            # auth_provider: Authentication Provider
        """
        if debug:
            logging.basicConfig(level=logging.DEBUG)

        # extract models from module
        all_models: {Model.__class__: [Model.__class__]} = {model: model.mro() for key in dir(models_module) if isinstance(model := getattr(models_module, key), Model.__class__) and model==model.mro()[0]}
        # collect parents models for hiding
        to_hide: set[Model.__class__] = set()
        [to_hide.update(m[1:]) for m in all_models.values()]
        # filter only top model names
        top_models = set(all_models.keys()) - to_hide
        # set global models list
        self.models = {m.__name__: m for m in top_models if m.__name__ not in exc_models}
        user_model: type[User] = self.models['User']
        pre_save(user_model)(hash_pwd)

        Tortoise.init_models([models_module], "models") # for relations

        pm_in = PydanticMeta
        pm_in.exclude_raw_fields = False
        pm_in.max_recursion = 0
        # pm_in.backward_relations = False
        pm_out = PydanticMeta
        pm_out.max_recursion = 1

        def gen_schemas(mdl: type[Model], key: str) -> (type[PydanticModel], type[PydanticModel]):
            return (
                # todo: why 'created_at' and 'updated_at' are not excluding from -In schema, cause they are readonly?
                pydantic_model_creator(mdl, name=key+'-In', meta_override=pm_in, exclude_readonly=True, exclude=('created_at', 'updated_at')),
                pydantic_model_creator(mdl, name=key, meta_override=pm_out)
            )

        schemas: {str: (type[PydanticModel], type[PydanticModel])} = {k: gen_schemas(m, k) for k, m in self.models.items()}

        # global user model inject current overriden User type # todo: maybe some refactor?
        oauth.UserSchema = schemas['User'][1]
        oauth.UserModel = user_model

        # get auth token route
        auth_routes = [
            APIRoute(self.prefix+'/register', reg_user, methods=['POST'], tags=['auth'], name='SignUp', response_model=schemas['User'][1]),
            APIRoute(self.prefix+'/token', login_for_access_token, methods=['POST'], response_model=Token, tags=['auth']),
        ]

        # main app
        self.app = FastAPI(debug=debug, routes=auth_routes, title=title, separate_input_output_schemas=False)

        # FastAPICache.init(InMemoryBackend(), expire=600)

        # build routes with schemas
        for name, schema in schemas.items():
            # in_model = pydantic_model_creator(self.models[name], name='New'+name, exclude_readonly=True).

            def _req2mod(req: Request) -> type[Model]:
                nam: str = req.scope['path'].split('/')[2]
                return self.models[nam]

            async def index(request: Request, limit: int = 50, page: int = 1):
                mod: Model.__class__ = _req2mod(request)
                data = await mod.pagePyd(limit, limit * (page - 1))
                # total = len(data) if len(data) < limit else await query.count()
                return data #, total  # show all

            async def one(request: Request, item_id: Annotated[int, Path()]):
                mod, pyd = _req2mod(request)
                try:
                    return await pyd[1].from_queryset_single(mod.get(id=item_id))  # show one
                except DoesNotExist as e:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

            async def upsert(request: Request, obj: schema[0], item_id: int|None = None):
                mod: type[Model] = obj.model_config['orig_model']
                pyd = _req2mod(request)[1][1]
                obj_dict = obj.model_dump()
                args = [obj_dict]
                if item_id:
                    args.append(item_id)
                try:
                    obj_db: Model = await mod.upsert(*args)
                except IntegrityError as e:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.__repr__())
                jsn: type[pyd] = await pyd.from_tortoise_orm(obj_db)
                return jsn

            async def delete(req: Request, item_id: int):
                mod, _ = _req2mod(req)
                try:
                    r = await mod.get(id=item_id).delete()
                    return {'deleted': r}
                except Exception as e:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.__repr__())

            ar = APIRouter(routes=[
                APIRoute('/'+name, index, methods=['GET'], name=name+' objects list', response_model=list[schema[1]]),
                APIRoute('/'+name, upsert, methods=['POST'], name=name+' object create', response_model=schema[1]),
                APIRoute('/'+name+'/{item_id}', one, methods=['GET'], name=name+' object get', response_model=schema[1]),
                APIRoute('/'+name+'/{item_id}', upsert, methods=['POST'], name=name+' object update', response_model=schema[1]),
                APIRoute('/'+name+'/{item_id}', delete, methods=['DELETE'], name=name+' object delete', response_model=dict),
            ])
            self.app.include_router(ar, prefix=self.prefix, tags=[name], dependencies=[Depends(get_current_user)])

        # db init
        load_dotenv()
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [models_module]}, generate_schemas=debug)
