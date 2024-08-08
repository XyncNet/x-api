from enum import Enum
from os import getenv as env
from aiogram.types import User as TgUser
from aiogram.utils.web_app import WebAppUser
from dotenv import load_dotenv
from xync_schema.models import User, UserStatus, Lang

load_dotenv()

TOKEN = env('TOKEN')
DB_URL = env('DB_URL')


async def user_upsert(u: TgUser | WebAppUser, status: UserStatus = None) -> (User, bool):
    pic = (gpp := await u.get_profile_photos(0, 1)).photos and gpp.photos[0][-1].file_unique_id if type(u) is TgUser else u.photo_url  # (u.photo_url[0] if u.photo_url else None)
    udf = {'username': u.username or u.id, 'first_name': u.first_name, 'last_name': u.last_name, 'status': UserStatus.MEMBER, 'lang': u.language_code and Lang[u.language_code], 'pic': pic}
    if status:
        udf.update({'status': status})
    return await User.update_or_create(udf, id=u.id)


def _repr(dct: dict, _names):
    try:
        return ' | '.join((item.name if isinstance(item := dct.pop(n), Enum) else str(item)) for n in _names)
    except KeyError:
        return dct['id']