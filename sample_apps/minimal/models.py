from tortoise import fields
from x_auth.enums import Scope
from x_auth.models import Model, User


class Story(Model):
    id: int = fields.IntField(pk=True)
    txt: str = fields.CharField(4095)
    user: User = fields.ForeignKeyField("models.User", related_name="stories")

    _name = ("id",)
    _allowed = Scope.READ + Scope.ALL + Scope.WRITE
