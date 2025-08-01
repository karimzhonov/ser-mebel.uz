from django import forms
from phonenumber_field.formfields import PhoneNumberField
from phonenumber_field.widgets import RegionalPhoneNumberWidget
from unfold.widgets import INPUT_CLASSES, AdminTextInputWidget
from client.models import Client

from .models import Invoice


class InvoiceCreateForm(forms.ModelForm):
    phone = PhoneNumberField(label="Телефон клиента", widget=RegionalPhoneNumberWidget('UZ', {'class': ' '.join(INPUT_CLASSES)}))
    fio = forms.CharField(label="ФИО клиента", widget=AdminTextInputWidget({'class': ' '.join(INPUT_CLASSES)}))

    class Meta:
        model = Invoice
        fields = ['fio', 'phone', 'desc']

    def save(self, commit=True):
        phone = self.cleaned_data['phone']
        fio = self.cleaned_data['fio']

        client, _ = Client.objects.get_or_create(phone=phone, defaults={'fio': fio})
        self.instance.client = client

        return super().save(commit=commit)
    