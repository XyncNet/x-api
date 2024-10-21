import models
from x_api.api import Api

dsn = "postgres://artemiev:@/test"
token = "6806432376:AAFdzMhrF0jpO88eWgH4J856lMfhYZT77zg"
api = Api(models, dsn, token, True)
api.gen_routes()
