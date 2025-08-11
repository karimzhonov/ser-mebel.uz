from django import forms
from phonenumber_field.formfields import PhoneNumberField
from phonenumber_field.widgets import RegionalPhoneNumberWidget
from unfold.widgets import INPUT_CLASSES, AdminTextInputWidget
from client.models import Client
from call_center.constants import SolutionChoice
from .models import Metering


class MeteringFromCallCenterForm(forms.ModelForm):
    class Meta:
        model = Metering
        fields = ['client', 'address', 'address_link', 'invoice']

    def save(self, commit: bool = True):
        if self.instance.invoice:
            self.instance.invoice.solution = SolutionChoice.sold_out
            self.instance.invoice.save()
        return super().save(commit)


class MeteringCreateForm(forms.ModelForm):
    phone = PhoneNumberField(label="Телефон клиента", widget=RegionalPhoneNumberWidget('UZ', {'class': ' '.join(INPUT_CLASSES)}))
    fio = forms.CharField(label="ФИО клиента", widget=AdminTextInputWidget({'class': ' '.join(INPUT_CLASSES)}))

    class Meta:
        model = Metering
        fields = ['fio', 'phone', 'address', 'address_link']

    def save(self, commit=True):
        phone = self.cleaned_data['phone']
        fio = self.cleaned_data['fio']

        client, _ = Client.objects.get_or_create(phone=phone, defaults={'fio': fio})
        self.instance.client = client

        return super().save(commit=commit)
    