from datetime import timedelta
from django.db.models import TextChoices
from django.db.models.functions import Now


class DashboardFilterChoices(TextChoices):
    year = 'year', 'Last year'
    month = 'month', 'Last month'
    week = 'week', 'Last week'

    @classmethod
    def filters(cls, choice, key):
        return {
            cls.year: {
                f"{key}__gte": Now() - timedelta(days=365)
            },
            cls.month: {
                f"{key}__gte": Now() - timedelta(days=30)
            },
            cls.week: {
                f"{key}__gte": Now() - timedelta(days=7)
            }
        }[choice]
