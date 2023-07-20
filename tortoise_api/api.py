import logging
from os import getenv as env
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates
from tortoise.contrib.starlette import register_tortoise
from tortoise_api_model import Model

from tortoise_api.util import jsonify


class Api:
    app: Starlette
    models: {str: Model}

    def __init__(
        self,
        debug: bool = False,
        # auth_provider: AuthProvider = None, # todo: add auth
    ):
        """
        Parameters:
            debug: Debug SQL queries, api requests
            # auth_provider: Authentication Provider
        """
        self.templates = Jinja2Templates("templates")
        self.routes: [Route] = [
            Route('/{model}/{oid}', self.api_one, methods=['GET', 'POST']),
            Route('/favicon.ico', lambda req: Response(), methods=['GET']),  # avoid chrome auto favicon load
            Route('/{model}', self.api_all, methods=['GET', 'POST']),
            Route('/', self.api_menu, methods=['GET']),
        ]
        self.debug = debug

    def start(self, models_module):
        self.models = {key: model for key in dir(models_module) if isinstance(model := getattr(models_module, key), type(Model)) and model.mro()[1]==Model}
        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
        self.app = Starlette(debug=self.debug, routes=self.routes)
        load_dotenv()
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [models_module]}, generate_schemas=self.debug)
        return self.app

    # ROUTES
    async def api_menu(self, _: Request):
        return JSONResponse(list(self.models))

    async def api_all(self, request: Request):
        model: Model = self._get_model(request)
        objects: [Model] = await model.all().prefetch_related(*model._meta.fetch_fields)
        data = [jsonify(obj) for obj in objects]
        return JSONResponse({'data': data})

    async def api_one(self, request: Request):
        model: Model = self._get_model(request)
        obj = await self._get_model(request).get(id=request.path_params['oid']).prefetch_related(*model._meta.fetch_fields)
        return JSONResponse(jsonify(obj))


    # UTILS
    def _get_model(self, request: Request) -> type(Model):
        model_id: str = request.path_params['model']
        return self.models.get(model_id)
