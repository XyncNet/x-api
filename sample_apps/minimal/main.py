from sample_apps.minimal import models
from tortoise_api import Api

app = Api(models, True)
