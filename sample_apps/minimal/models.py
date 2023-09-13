from tortoise import fields
from tortoise_api_model import Model
from tortoise_api_model.model import User


class Post(Model):
    id: int = fields.IntField(pk=True)
    text: str = fields.CharField(4095)
    user: User = fields.ForeignKeyField('models.User', related_name='posts')

    _name = 'text'
