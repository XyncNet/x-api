import logging
from functools import reduce
from os import getenv as env
from types import ModuleType
from typing import Annotated, Type
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Path, HTTPException
from fastapi.routing import APIRoute, APIRouter
from pydantic import BaseModel, ConfigDict, create_model
# from fastapi_cache import FastAPICache
# from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette import status
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.types import Lifespan
from tortoise import Tortoise, ModelMeta
from tortoise.contrib.pydantic import PydanticModel
from tortoise.contrib.starlette import register_tortoise
from tortoise.exceptions import IntegrityError, DoesNotExist

from tortoise_api_model.model import Model
from tortoise_api_model.pydantic import PydList

from tortoise_api.oauth import OAuth


class ListArgs(BaseModel):
    model_config = ConfigDict(extra='allow')
    limit: int = 100
    offset: int = 0
    sort: str | None = '-id'
    q: str | None = None


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
            exc_models: set[str] = None,
            lifespan: Lifespan = None,
            tg_auth: bool = False
    ):
        """
        Parameters:
            debug: Debug SQL queries, api requests
            # auth_provider: Authentication Provider
        """
        load_dotenv()

        if debug:
            logging.basicConfig(level=logging.DEBUG)

        # extract models from module
        models_trees: {Model.__class__: [Model.__class__]} = {mdl: mdl.mro() for key in dir(module) if isinstance(mdl := getattr(module, key), Model.__class__)}
        # collect not top (bottom) models for removing
        bottom_models: {Model.__class__} = reduce(lambda x, y: x | set(y[1:]), models_trees.values(), {object}) & set(models_trees)
        # filter only top model names
        mm = {m: v for m in dir(module) if isinstance(v := getattr(module, m), ModelMeta)}
        [delattr(module, n) for n, m in mm.items() if m in bottom_models]
        top_models = set(models_trees.keys()) - bottom_models
        # set global models list
        self.models = {m.__name__: m for m in top_models if not exc_models or m.__name__ not in exc_models}

        Tortoise.init_models([module], "models")  # for relations

        schemas: {str: (Type[PydanticModel], Type[PydanticModel], Type[PydList])} = {k: (
            m.pyd(),
            m.pydIn(),
            m.pydsList()
        ) for k, m in self.models.items()}

        # get auth token route
        self.oauth = OAuth(env('TOKEN'), self.models['User'])
        auth_routes = [
            APIRoute('/register', self.oauth.reg_user, methods=['POST'], tags=['auth'], name='SignUp', response_model=self.oauth.Token),
            APIRoute('/token', self.oauth.login_for_access_token, methods=['POST'], response_model=self.oauth.Token, tags=['auth'], operation_id='token'),
        ]

        # main app
        self.app = FastAPI(debug=debug, routes=auth_routes, title=title, separate_input_output_schemas=False, lifespan=lifespan)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # FastAPICache.init(InMemoryBackend(), expire=600)

        # build routes with schemas
        for name, schema in schemas.items():
            def _req2mod(req: Request) -> Type[Model]:
                nam: str = req.scope['path'].split('/')[2]
                return self.models[nam]

            DynamicListRequestModel = create_model(
                name+'ListRequest', q=(str, ''), __base__=ListArgs
            )

            async def index(request: Request, params: DynamicListRequestModel) -> schema[2]:
                mod: Model.__class__ = _req2mod(request)
                sorts = [params.sort] if params.sort else mod._sorts
                data = await mod.pagePyd(sorts, params.limit, params.offset, params.q, **params.model_extra)
                return data

            async def one(request: Request, item_id: Annotated[int, Path()]):
                mod = _req2mod(request)
                try:
                    return await mod.one(item_id)  # show one
                except DoesNotExist:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

            async def upsert(obj: schema[1], item_id: int | None = None):
                mod: Type[Model] = obj.model_config['orig_model']
                obj_dict = obj.model_dump()
                args = [obj_dict]
                if item_id:
                    args.append(item_id)
                try:
                    obj_db: Model = await mod.upsert(*args)
                except IntegrityError as e:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.__repr__())
                # pyd: PydanticModel = await mod.pyd().from_tortoise_orm(obj_db)
                pyd = await mod.one(obj_db.id)  # todo: double request, dirty fix for buildint in topli with recursion=2
                return pyd

            async def delete(req: Request, item_id: int):
                mod = _req2mod(req)
                try:
                    r = await mod.get(id=item_id).delete()
                    return {'deleted': r}
                except Exception as e:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.__repr__())

            ar = APIRouter(routes=[
                APIRoute('/'+name, index, methods=['POST'], name=name+' objects list', response_model=schema[2]),
                APIRoute('/'+name, upsert, methods=['PUT'], name=name+' object create', response_model=schema[0]),
                APIRoute('/'+name+'/{item_id}', one, methods=['GET'], name=name+' object get', response_model=schema[0]),
                APIRoute('/'+name+'/{item_id}', upsert, methods=['PATCH'], name=name+' object update', dependencies=[self.oauth.write], response_model=schema[0]),
                APIRoute('/'+name+'/{item_id}', delete, methods=['DELETE'], name=name+' object delete', dependencies=[self.oauth.my], response_model=dict),
            ])
            self.app.include_router(ar, prefix=self.prefix, tags=[name], dependencies=[Depends(self.oauth.get_current_user)])

        # db init
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [module]}, generate_schemas=debug)
