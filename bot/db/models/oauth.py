from tortoise import Model, fields


class User(Model):
    id = fields.IntField(primary_key=True)
    phone = fields.CharField(max_length=255)
    name = fields.CharField(max_length=255, null=True)
    telegram_id = fields.BigIntField(null=True)
    is_staff = fields.BooleanField(default=False)
    is_active = fields.BooleanField(default=True)
