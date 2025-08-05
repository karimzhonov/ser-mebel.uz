from django import forms

from metering.constants import MeteringStatus
from call_center.constants import SolutionChoice
from .models import Order


class OrderAddForm(forms.ModelForm):

    class Meta:
        model = Order
        fields = "__all__"

    def save(self, commit=True):
        if self.instance.metering:
            self.instance.metering.status = MeteringStatus.sold_out
            self.instance.metering.save()
            print(self.instance.metering.invoice)
            if self.instance.metering.invoice:
                self.instance.metering.invoice.solution = SolutionChoice.sold_out
                self.instance.metering.invoice.save()
        return super().save(commit)