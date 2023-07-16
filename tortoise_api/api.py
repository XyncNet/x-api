import logging
from datetime import datetime
from inspect import getmembers
from os import getenv as env
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates
from tortoise import Model
from tortoise.contrib.starlette import register_tortoise
from tortoise.queryset import QuerySet


class Api:
    app: Starlette
    def __init__(
        self,
        models_module,
        debug: bool = False,
        as_dict: bool = True
        # auth_provider: AuthProvider = None, # todo: add auth
    ):
        """
        Parameters:
            models_module: Admin title.
            # auth_provider: Authentication Provider
        """
        self.as_dict: bool = as_dict
        models = getmembers(models_module)
        self.models: {str: Model} = {k: v for k, v in models if isinstance(v, type(Model)) and v.mro()[0] != Model}
        self.templates = Jinja2Templates("templates")
        self.routes: [Route] = [
            Route('/', self.menu, methods=['GET']),
            Route('/{model}', self.api_all, methods=['GET', 'POST']),
            Route('/{model}/{oid}', self.api_one, methods=['GET', 'POST']),
        ]
        self.debug = debug
        self.models_module = models_module


    def app(self):
        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
        self.app = Starlette(debug=self.debug, routes=self.routes)
        load_dotenv()
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [self.models_module]}, generate_schemas=self.debug)
        return self.app


    # ROUTES
    async def menu(self, _: Request):
        body: str = '<br>'.join(f'<a href="/{model}">{model}</a>' for model in self.models)
        return HTMLResponse(body)

    async def api_all(self, request: Request):
        fn: callable = QuerySet.values if self.as_dict else QuerySet.values_list
        data = await fn(self._get_model(request).all())
        return JSONResponse({'data': self._jsonify(data)})

    async def api_one(self, request: Request):
        obj = await self._get_model(request).get(id=request.path_params['oid']).values()
        return JSONResponse(self._jsonify([obj])[0])


    # UTILS
    def _get_model(self, request: Request) -> type(Model):
        model_id: str = request.path_params['model']
        return self.models[model_id]

    def _jsonify(self, data: [Model]):
        trans_type_json = {
            datetime: lambda x: x.__str__().split('+')[0]
        }
        if self.as_dict:
            return [{k: fn(v) if (fn := trans_type_json.get(type(v))) else v for k, v in d.items()} for d in data]
        # format for datatables
        return [[fn(v) if (fn := trans_type_json.get(type(v))) else v for v in d] for d in data]
