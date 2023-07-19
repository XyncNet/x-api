from antifragility_schema import models
from tortoise_api import Api

app = Api(models, True)
