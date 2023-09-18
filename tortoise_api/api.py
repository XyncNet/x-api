import logging
from os import getenv as env
from types import ModuleType
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from fastapi.responses import ORJSONResponse
from fastapi.routing import APIRoute, APIRouter
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache
from starlette.requests import Request
from starlette.responses import JSONResponse
from tortoise.contrib.pydantic import pydantic_model_creator, PydanticModel
from tortoise.contrib.starlette import register_tortoise

from tortoise_api_model import Model

from tortoise_api import oauth
from tortoise_api.oauth import login_for_access_token, Token, get_current_user, reg_user
from tortoise_api.util import jsonify, delete


class Api:
    app: FastAPI
    models: {str: Model}

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
        models: {Model.__class__: [Model.__class__]} = {model: model.mro() for key in dir(models_module) if isinstance(model := getattr(models_module, key), Model.__class__) and model==model.mro()[0]}
        # collect parents models for hiding
        to_hide: set[Model.__class__] = set()
        [to_hide.update(m[1:]) for m in models.values()]
        # set global only top models list
        self.models: {str: Model.__class__} = {m.__name__: m for m in set(models.keys()) - to_hide}
        oauth.user_model = self.models.get('User')
        # get auth token route
        auth_routes = [
            APIRoute('/register', reg_user, methods=['POST'], tags=['auth'], name='SignUp'),
            APIRoute('/token', login_for_access_token, methods=['POST'], response_model=Token, tags=['auth']),
        ]

        # main app
        self.app = FastAPI(debug=debug, routes=auth_routes, title=title)
        # api routes
        api_router = APIRouter(routes=[
            APIRoute('/models', self.api_menu, name='All models description'),
            APIRoute('/model/{model}', self.all, methods=['GET'], name='Dynamic model objects list'),
            APIRoute('/model/{model}', self.create, methods=['POST'], name='Dynamic model object create'),
            APIRoute('/model/{model}/{oid}', self.one_get, methods=['GET'], name='Dynamic model object get'),
            APIRoute('/model/{model}/{oid}', self.one_update, methods=['POST'], name='Dynamic model object update'),
            APIRoute('/model/{model}/{oid}', self.one_delete, methods=['DELETE'], name='Dynamic model object delete'),
        ])
        self.app.include_router(api_router, tags=["api"], dependencies=[Depends(get_current_user)])
        # db init
        load_dotenv()
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [models_module]}, generate_schemas=debug)
        FastAPICache.init(InMemoryBackend(), expire=600)


    # ROUTES
    @cache()
    async def api_menu(self):
        pm: type[PydanticModel]
        mds: {str: {str: Any}} = {n: pydantic_model_creator(m).model_json_schema()['properties'] for n, m in self.models.items()}
        return ORJSONResponse(mds)


    async def create(self, data: dict, model: str):
        model: type[Model] = self.models.get(model)
        obj: Model = await model.upsert(data)
        jsn: dict = await jsonify(obj)
        return ORJSONResponse(jsn, status_code=201) # create

    async def all(self, model: str, limit: int = 50, page: int = 1):
        model: type[Model] = self.models.get(model)
        objects: [Model] = await model.all().prefetch_related(*model._meta.fetch_fields).limit(limit).offset(limit*(page-1))
        data = [await jsonify(obj) for obj in objects]
        return JSONResponse({'data': data}) # show all

    async def one_get(self, model: str, oid: int):
        model: type[Model] = self.models.get(model)
        obj = await model.get(id=oid).prefetch_related(*model._meta.fetch_fields)
        return JSONResponse(await jsonify(obj)) # show one

    async def one_update(self, data: dict, model: str, oid: int):
        model: type[Model] = self.models.get(model)
        obj: Model = await model.upsert(data, oid)
        jsn: dict = await jsonify(obj)
        return ORJSONResponse(jsn, status_code=202) # update

    async def one_delete(self, request: Request, model: str, oid: int):
        model: type[Model] = self.models.get(model)
        await delete(model, oid)
        return JSONResponse({}, status_code=202) # delete
