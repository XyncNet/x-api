import logging
from datetime import datetime
from inspect import getmembers

from os import getenv as env
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates
from tortoise import Model
from tortoise.contrib.starlette import register_tortoise


class Api:
    def __init__(
        self,
        models_module,
        debug: bool = False,
        # auth_provider: Optional[AuthProvider] = None,
    ):
        """
        Parameters:
            models_module: Admin title.
            # auth_provider: Authentication Provider
        """
        self.routes: [Route] = []
        models = getmembers(models_module)
        self.models: {str: Model} = {k: v for k, v in models if isinstance(v, type(Model))}
        self.templates = Jinja2Templates("templates")

        self.app = Starlette(debug=debug, routes=[
            Route('/{model}', self.index, methods=['GET', 'POST']),
            # Route('/{user_id}', user),
        ])

        load_dotenv()
        register_tortoise(self.app, db_url=env("DB_URL"), modules={"models": [models_module]}, generate_schemas=debug)

        if debug:
            logging.basicConfig(level=logging.DEBUG)


    # ROUTES
    async def index(self, request: Request):
        data = await self._get_model(request).all().values_list()
        return JSONResponse({'data': self.jsonify(data)})


    # UTILS
    def _get_model(self, request: Request) -> type(Model):
        model_id: str = request.path_params['model']
        return self.models[model_id]

    @staticmethod
    def jsonify(data: [Model]):
        trans_type_json = {
            datetime: lambda x: x.__str__().split('+')[0]
        }
        return [[fn(v) if (fn := trans_type_json.get(type(v))) else v for v in d] for d in data]
