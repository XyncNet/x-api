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

from tortoise_api.util import _api_repr


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
        for_dt: bool = False
        # auth_provider: AuthProvider = None, # todo: add auth
    ):
        """
        Parameters:
            models_module: Admin title.
            # auth_provider: Authentication Provider
        """
        self.for_dt: bool = for_dt
        models = getmembers(models_module)
        self.models: {str: Model} = {k: v for k, v in models if isinstance(v, type(Model)) and v.mro()[0] != Model}
        self.templates = Jinja2Templates("templates")
        self.routes: [Route] = [
            Route('/{model}/{oid}', self.api_one, methods=['GET', 'POST']),
            Route('/favicon.ico', lambda req: Response(), methods=['GET']),
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
        # body: str = '<br>'.join(f'<a href="/{model}">{model}</a>' for model in )
        return JSONResponse(list(self.models))

    async def api_all(self, request: Request):
        model: Model = self._get_model(request)
        objects: [{str: Model}] = await model.all().prefetch_related(*model._meta.fetch_fields)
        data = self._jsonify(objects)
        # if self.for_dt:
        #     data = [d.values() for d in data]
        return JSONResponse({'data': data})

    async def api_one(self, request: Request):
        obj = await self._get_model(request).get(id=request.path_params['oid']).values()
        return JSONResponse(self._jsonify([obj])[0])


    # UTILS
    def _get_model(self, request: Request) -> type(Model):
        model_id: str = request.path_params['model']
        return self.models.get(model_id)


    def _jsonify(self, data: [Model]):
        # if self.for_dt:
        #     # format for datatables
        #     return [[fn(v) if (fn := trans_type_json.get(type(v))) else v for v in d] for d in data]
        return [_api_repr(d) for d in data]
