import logging
from inspect import getmembers
from os import getenv as env
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates
from tortoise import Model as BaseModel
from tortoise.contrib.starlette import register_tortoise

from tortoise_api.util import jsonify


class Model(BaseModel):
    _name: str = 'name'
    def repr(self):
        if self._name in self._meta.db_fields:
            return getattr(self, self._name)
        return self.__repr__()


class Api:
    app: Starlette
    def __init__(
        self,
        models_module,
        debug: bool = False,
        # auth_provider: AuthProvider = None, # todo: add auth
    ):
        """
        Parameters:
            models_module: Admin title.
            # auth_provider: Authentication Provider
        """
        models = getmembers(models_module)
        self.models: {str: Model} = {k: v for k, v in models if isinstance(v, type(Model)) and v.mro()[0] != Model}
        self.templates = Jinja2Templates("templates")
        self.routes: [Route] = [
            Route('/{model}/{oid}', self.api_one, methods=['GET', 'POST']),
            Route('/favicon.ico', lambda req: Response(), methods=['GET']),  # avoid chrome auto favicon load
            Route('/{model}', self.api_all, methods=['GET', 'POST']),
            Route('/', self.api_menu, methods=['GET']),
        ]
        self.debug = debug
        self.models_module = models_module

    def start(self):
        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
        self.app = Starlette(debug=self.debug, routes=self.routes)
        load_dotenv()
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [self.models_module]}, generate_schemas=self.debug)
        return self.app

    # ROUTES
    async def api_menu(self, _: Request):
        return JSONResponse(list(self.models))

    async def api_all(self, request: Request):
        model: Model = self._get_model(request)
        objects: [{str: Model}] = await model.all().prefetch_related(*model._meta.fetch_fields)
        data = [jsonify(d) for d in objects]
        return JSONResponse({'data': data})

    async def api_one(self, request: Request):
        model: Model = self._get_model(request)
        obj = await self._get_model(request).get(id=request.path_params['oid']).prefetch_related(*model._meta.fetch_fields)
        return JSONResponse(jsonify(obj))


    # UTILS
    def _get_model(self, request: Request) -> type(Model):
        model_id: str = request.path_params['model']
        return self.models.get(model_id)
