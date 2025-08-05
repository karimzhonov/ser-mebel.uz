from django.db.models import TextChoices


class Currency(TextChoices):
    dollar = ('$', 'Доллар($)')
    sum = ('sum', 'Сўм')
