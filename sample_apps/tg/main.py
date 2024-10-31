from dotenv import load_dotenv
from os import getenv as env

from tg_auth.router import TgRouter

from x_api.api import Api

import model

load_dotenv()

api = Api(model, env("DB_URL"), env("SECRET"), TgRouter, True)

api.gen_routes()
