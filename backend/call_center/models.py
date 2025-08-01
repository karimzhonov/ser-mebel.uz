from django.db import models
from .constants import SolutionChoice


class Invoice(models.Model):
    client = models.ForeignKey('client.Client', models.PROTECT, verbose_name='Мижоз')
    create_date = models.DateTimeField('Дата создание', auto_now_add=True)
    update_date = models.DateTimeField('Дата изменение', auto_now=True)
    desc = models.TextField('Описание')
    solution = models.IntegerField('Код ответа', choices=SolutionChoice.choices, default=None, null=True)

    class Meta:
        verbose_name = 'Заяавка'
        verbose_name_plural = 'Заяавки'

    def __str__(self):
        return str(self.client)

    def send_location(self, callback = None):
        # TODO: send location from SMS
        flag = True
        if callable(callback): callback(flag)
