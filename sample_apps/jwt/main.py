import model
from x_api.api import Api

dsn = "postgres://artemiev:@/test"
token = "6806432376:AAFdzMhrF0jpO88eWgH4J856lMfhYZT77zg"
api = Api(model, dsn, token)
api.gen_routes()
