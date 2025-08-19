from django import forms
from unfold.widgets import SELECT_CLASSES
from metering.constants import MeteringStatus
from metering.models import Metering
from call_center.constants import SolutionChoice
from metering.design.models import DesignType
from .models import Order


class OrderAddForm(forms.ModelForm):
    design_type = forms.ModelChoiceField(queryset=DesignType.objects)

    class Meta:
        model = Order
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['design_type'].widget.attrs['class'] = ' '.join(SELECT_CLASSES)

        metering_id = self.initial.get('metering') or self.instance.metering_id

        if metering_id:
            metering = Metering.objects.prefetch_related(
                'design'
            ).get(pk=metering_id)

            self.fields['design_type'].queryset = DesignType.objects.filter(
                design=metering.design
            )

    def save(self, commit=True):
        if self.instance.metering:
            self.instance.metering.status = MeteringStatus.sold_out
            self.instance.metering.save()
            if self.instance.metering.invoice:
                self.instance.metering.invoice.solution = SolutionChoice.sold_out
                self.instance.metering.invoice.save()
        return super().save(commit)