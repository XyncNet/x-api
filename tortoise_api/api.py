import logging
from functools import reduce
from os import getenv as env
from types import ModuleType
from typing import Annotated, Type
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Path, HTTPException
from fastapi.routing import APIRoute, APIRouter
# from fastapi_cache import FastAPICache
# from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette import status
from starlette.requests import Request
from tortoise import Tortoise, ModelMeta
from tortoise.contrib.pydantic import PydanticModel, PydanticListModel
from tortoise.contrib.starlette import register_tortoise
from tortoise.exceptions import IntegrityError, DoesNotExist

from tortoise_api_model.model import Model, User as UserModel, UserUpdate
from tortoise_api.oauth import login_for_access_token, Token, get_current_user, reg_user, write, my


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
        # mm = {m: v for m in dir(module) if isinstance(v:=getattr(module, m), ModelMeta)}
        # [delattr(module, m.__name__) for m in bottom_models if m in mm.values()]
        top_models = set(models_trees.keys()) - bottom_models
        # set global models list
        self.models = {m.__name__: m for m in top_models if m.__name__ not in exc_models}

        Tortoise.init_models([module], "models") # for relations

        schemas: {str: (Type[PydanticModel], Type[PydanticModel], Type[PydanticListModel])} = {k: (m.pyd(), UserUpdate if k=='User' else m.pyd(True), m.pyds()) for k, m in self.models.items()}

        # get auth token route
        auth_routes = [
            APIRoute('/register', reg_user, methods=['POST'], tags=['auth'], name='SignUp', response_model=Token),
            APIRoute('/token', login_for_access_token, methods=['POST'], response_model=Token, tags=['auth']),
        ]

        # main app
        self.app = FastAPI(debug=debug, routes=auth_routes, title=title, separate_input_output_schemas=False)

        # FastAPICache.init(InMemoryBackend(), expire=600)

        # build routes with schemas
        for name, schema in schemas.items():
            def _req2mod(req: Request) -> Type[Model]:
                nam: str = req.scope['path'].split('/')[2]
                return self.models[nam]

            async def index(request: Request, limit: int = 1000, offset: int = 0) -> schema[2]:
                mod: Model.__class__ = _req2mod(request)
                data = await mod.pagePyd(limit, offset)
                return data

            async def one(request: Request, item_id: Annotated[int, Path()]):
                mod = _req2mod(request)
                try:
                    q = mod.get(id=item_id)
                    return UserUpdate.model_validate(q, from_attributes=True) if name=='User' else await mod.pyd().from_queryset_single(q)  # show one
                except DoesNotExist as e:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

            async def upsert(obj: schema[1], item_id: int|None = None):
                mod: Type[Model] = obj.model_config.get('orig_model', UserModel)
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
                APIRoute('/'+name, upsert, methods=['POST'], name=name+' object create', dependencies=[write], response_model=schema[0]),
                APIRoute('/'+name+'/{item_id}', one, methods=['GET'], name=name+' object get', response_model=schema[0]),
                APIRoute('/'+name+'/{item_id}', upsert, methods=['POST'], name=name+' object update', dependencies=[write], response_model=schema[0]),
                APIRoute('/'+name+'/{item_id}', delete, methods=['DELETE'], name=name+' object delete', dependencies=[my], response_model=dict),
            ])
            self.app.include_router(ar, prefix=self.prefix, tags=[name], dependencies=[Depends(get_current_user)])

        # db init
        load_dotenv()
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [module]}, generate_schemas=debug)
