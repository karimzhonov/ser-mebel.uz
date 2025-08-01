from django.db.models import Manager
from django.db.models.query import QuerySet
from django.db.models import ExpressionWrapper, F, DurationField
from django.db.models.functions import Now, ExtractDay

class OrderManager(Manager):
    def get_queryset(self) -> QuerySet:
        return super().get_queryset().annotate(
            days=ExtractDay(ExpressionWrapper(
                F('end_date') - Now(),
                output_field=DurationField()
            ))
        )