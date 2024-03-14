import models
from tortoise_api import Api

api = Api(models, True)
api.gen_routes()
