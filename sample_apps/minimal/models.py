from tortoise import fields
from tortoise_api_model import Model
from tortoise_api_model.model import User


class Story(Model):
    id: int = fields.IntField(pk=True)
    txt: str = fields.CharField(4095)
    user: User = fields.ForeignKeyField('models.User', related_name='stories')

    _name = 'id'
