from tortoise_api.api import Api
from sample_apps.minimal import models

app = Api(models, True).app
