from django.db.models import IntegerChoices
from .models import ExpenseCategory, Expense


class DefaultExpenseCategoryChoices(IntegerChoices):
    design = (1, 'Услега дизайна')
    rover = (2, 'Услуга ровера')
    painter = (3, 'Услуга мольяра')
    assembly = (4, 'Услуга сборка/установка')

    @classmethod
    def update_or_create_expense(cls, category_id, order=None):
        category, _ = ExpenseCategory.objects.update_or_create(
            id=category_id,
            defaults={
                "name": cls(category_id).label
            }
        )

        return Expense.objects.update_or_create(
            order=order,
            category=category,
            defaults={
                'cost': order.price
            }
        )