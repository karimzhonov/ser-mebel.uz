from django.db.models import DurationField, ExpressionWrapper, F, Manager
from django.db.models.functions import ExtractDay, Now
from django.db.models.query import QuerySet


class OrderManager(Manager):
    def get_queryset(self) -> QuerySet:
        return (
            super()
            .get_queryset()
            .annotate(
                days=ExtractDay(
                    ExpressionWrapper(F("end_date") - Now(), output_field=DurationField())
                )
            )
        )
