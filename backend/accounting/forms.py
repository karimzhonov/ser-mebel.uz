from django import forms
from order.constants import OrderStatus
from order.models import Order

from .models import Expense


class ExpenseForm(forms.ModelForm):
    
    class Meta:
        model = Expense
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['order'].queryset = Order.objects.exclude(status=OrderStatus.DONE)
