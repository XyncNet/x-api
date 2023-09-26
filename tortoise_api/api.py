import logging
from os import getenv as env
from types import ModuleType
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Path
from fastapi.responses import ORJSONResponse
from fastapi.routing import APIRoute, APIRouter
# from fastapi_cache import FastAPICache
# from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse
from tortoise import Tortoise
from tortoise.contrib.pydantic import pydantic_model_creator, PydanticModel
from tortoise.contrib.pydantic.creator import PydanticMeta
from tortoise.contrib.starlette import register_tortoise
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

    def __init__(
        self,
        models_module: ModuleType,
        debug: bool = False,
        title: str = 'FemtoAPI',
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
        self.models = {m.__name__: m for m in top_models}
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
            return pydantic_model_creator(mdl, name=key+'-In', meta_override=pm_in, exclude_readonly=True),  pydantic_model_creator(mdl, name=key, meta_override=pm_out)


        schemas: {str: (type[PydanticModel], type[PydanticModel])} = {k: gen_schemas(m, k) for k, m in self.models.items()}

        # global user model inject current overriden User type # todo: maybe some refactor?
        oauth.UserSchema = schemas['User'][1]
        oauth.UserModel = user_model

        # get auth token route
        auth_routes = [
            APIRoute('/register', reg_user, methods=['POST'], tags=['auth'], name='SignUp', response_model=schemas['User'][1]),
            APIRoute('/token', login_for_access_token, methods=['POST'], response_model=Token, tags=['auth']),
        ]

        # main app
        self.app = FastAPI(debug=debug, routes=auth_routes, title=title, default_response_class=ORJSONResponse, separate_input_output_schemas=False)

        # FastAPICache.init(InMemoryBackend(), expire=600)

        # build routes with schemas
        for name, schema in schemas.items():
            # in_model = pydantic_model_creator(self.models[name], name='New'+name, exclude_readonly=True).

            def _req2mod(req: Request) -> (type[Model], type[PydanticModel]):
                nam: str = req.scope['path'].split('/')[1]
                return self.models[nam], schemas[nam]

            async def index(request: Request, limit: int = 50, page: int = 1):
                mod, pyd = _req2mod(request)
                objects: QuerySet[Model] = mod.all().limit(limit).offset(limit * (page - 1))
                data = await pyd[1].from_queryset(objects)
                return data  # show all

            async def one(request: Request, item_id: Annotated[int, Path(title=name+" ID")]):
                mod, pyd = _req2mod(request)
                return await pyd[1].from_queryset_single(mod[item_id])  # show one

            async def create(obj: schema[0]):
                mod: type[Model] = obj.model_config['orig_model']
                obj_dict = obj.model_dump()
                obj_db: Model = await model.upsert(obj_dict)
                jsn: type[schema[1]] = await schema[1].model_validate(obj_db, from_attributes=True)
                return ORJSONResponse(jsn, status_code=status.HTTP_201_CREATED)  # create

            async def update(obj: schema[0], item_id: int):
                mod: type[Model] = obj.model_config['orig_model']
                obj_db: Model = await model.upsert(obj.model_dump(), item_id)
                jsn: type[schema[1]] = await schema[1].model_validate(obj_db, from_attributes=True)
                return ORJSONResponse(jsn, status_code=status.HTTP_202_ACCEPTED)  # update

            async def delete(req: Request, item_id: int):
                mod, _ = _req2mod(req)
                await (await mod[item_id]).delete()
                return JSONResponse(True, status_code=status.HTTP_205_RESET_CONTENT)  # delete

            ar = APIRouter(routes=[
                APIRoute('/'+name, index, methods=['GET'], name=name+' objects list', response_model=list[schema[1]]),
                APIRoute('/'+name, create, methods=['POST'], name=name+' object create', response_model=schema[1], description='321321'),
                APIRoute('/'+name+'/{item_id}', one, methods=['GET'], name=name+' object get', response_model=schema[1]),
                APIRoute('/'+name+'/{item_id}', update, methods=['POST'], name=name+' object update', response_model=schema[1]),
                APIRoute('/'+name+'/{item_id}', delete, methods=['DELETE'], name=name+' object delete', response_model=bool),
            ])
            self.app.include_router(ar, tags=[name], dependencies=[Depends(get_current_user)])

        # db init
        load_dotenv()
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [models_module]}, generate_schemas=debug)
