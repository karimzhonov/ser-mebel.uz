from django import forms
from call_center.constants import SolutionChoice
from .models import Metering


class MeteringCreateForm(forms.ModelForm):
    class Meta:
        model = Metering
        fields = ['client', 'address', 'address_link', 'invoice', 'date_time']

    def save(self, commit: bool = True):
        instance: Metering = super().save(commit)
        if instance.invoice:
            instance.invoice.solution = SolutionChoice.go_for_measured
            instance.invoice.save()
        return instance 
    