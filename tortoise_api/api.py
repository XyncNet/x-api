import logging
from functools import reduce
from os import getenv as env
from types import ModuleType
from typing import Annotated, Type

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Path, HTTPException, Form
from fastapi.routing import APIRoute, APIRouter
# from fastapi_cache import FastAPICache
# from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette import status
from starlette.requests import Request
from tortoise import Tortoise, ModelMeta
from tortoise.contrib.pydantic import pydantic_model_creator, PydanticModel, PydanticListModel
from tortoise.contrib.pydantic.creator import PydanticMeta
from tortoise.contrib.starlette import register_tortoise
from tortoise.exceptions import IntegrityError, DoesNotExist
from tortoise.signals import pre_save

from tortoise_api_model.model import hash_pwd, Model, User as UserModel
from tortoise_api.oauth import login_for_access_token, Token, get_current_user, reg_user


class Api:
    app: FastAPI
    models: {str: Model}
    redis = None
    prefix = '/v2'

    def __init__(
        self,
        module: ModuleType,
        debug: bool = False,
        title: str = 'FemtoAPI',
        exc_models: set[str] = set(),
    ):
        """
        Parameters:
            debug: Debug SQL queries, api requests
            # auth_provider: Authentication Provider
        """
        if debug:
            logging.basicConfig(level=logging.DEBUG)

        # extract models from module
        models_trees: {Model.__class__: [Model.__class__]} = {mdl: mdl.mro() for key in dir(module) if isinstance(mdl := getattr(module, key), Model.__class__)}
        # collect not top (bottom) models for removing
        bottom_models: {Model.__class__} = reduce(lambda x,y: x | set(y[1:]), models_trees.values(), {object}) & set(models_trees)
        # filter only top model names
        mm = {m: v for m in dir(module) if isinstance(v:=getattr(module, m), ModelMeta)}
        [delattr(module, m.__name__) for m in bottom_models if m in mm.values()]
        top_models = set(models_trees.keys()) - bottom_models
        # set global models list
        self.models = {m.__name__: m for m in top_models if m.__name__ not in exc_models}
        # pre_save(user_model)(hash_pwd)

        Tortoise.init_models([module], "models") # for relations

        schemas: {str: (Type[PydanticModel], Type[PydanticModel], Type[PydanticListModel])} = {k: (m.pyd(), m.pyd(True), m.pyds()) for k, m in self.models.items()}

        # get auth token route
        auth_routes = [
            APIRoute('/register', reg_user, methods=['POST'], tags=['auth'], name='SignUp', response_model=UserModel.pyd()),
            APIRoute('/token', login_for_access_token, methods=['POST'], response_model=Token, tags=['auth']),
        ]

        # main app
        self.app = FastAPI(debug=debug, routes=auth_routes, title=title, separate_input_output_schemas=False)

        # FastAPICache.init(InMemoryBackend(), expire=600)

        # build routes with schemas
        for name, schema in schemas.items():
            # in_model = pydantic_model_creator(self.models[name], name='New'+name, exclude_readonly=True).

            def _req2mod(req: Request) -> Type[Model]:
                nam: str = req.scope['path'].split('/')[2]
                return self.models[nam]

            async def index(request: Request, limit: int = 1000, offset: int = 0) -> schema[2]:
                mod: Model.__class__ = _req2mod(request)
                data = await mod.pagePyd(limit, offset)
                # total = len(data) if len(data) < limit else await query.count()
                return data # {'data': data, 'total': total}  # show all

            async def one(request: Request, item_id: Annotated[int, Path()]):
                mod = _req2mod(request)
                try:
                    return await mod.pyd().from_queryset_single(mod.get(id=item_id))  # show one
                except DoesNotExist as e:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

            async def upsert(request: Request, obj: schema[1], item_id: int|None = None):
                mod: Type[Model] = obj.model_config['orig_model']
                obj_dict = obj.model_dump()
                args = [obj_dict]
                if item_id:
                    args.append(item_id)
                try:
                    obj_db: Model = await mod.upsert(*args)
                except IntegrityError as e:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.__repr__())
                jsn: PydanticModel = await mod.pyd().from_tortoise_orm(obj_db)
                return jsn

            async def delete(req: Request, item_id: int):
                mod = _req2mod(req)
                try:
                    r = await mod.get(id=item_id).delete()
                    return {'deleted': r}
                except Exception as e:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.__repr__())

            ar = APIRouter(routes=[
                APIRoute('/'+name, index, methods=['GET'], name=name+' objects list', response_model=schema[2]),
                APIRoute('/'+name, upsert, methods=['POST'], name=name+' object create', response_model=schema[0]),
                APIRoute('/'+name+'/{item_id}', one, methods=['GET'], name=name+' object get', response_model=schema[0]),
                APIRoute('/'+name+'/{item_id}', upsert, methods=['POST'], name=name+' object update', response_model=schema[0]),
                APIRoute('/'+name+'/{item_id}', delete, methods=['DELETE'], name=name+' object delete', response_model=dict),
            ])
            self.app.include_router(ar, prefix=self.prefix, tags=[name], dependencies=[Depends(get_current_user)])

        # db init
        load_dotenv()
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [module]}, generate_schemas=debug)
