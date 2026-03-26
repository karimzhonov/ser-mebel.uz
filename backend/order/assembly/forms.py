from django import forms
from django.db.models import Q
from unfold.widgets import UnfoldAdminSelectWidget
from oauth.models import User
from oauth.constants import ASSEMBLY_PERMISSION
from .models import Assembly


class AssemblyForm(forms.ModelForm):
    user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        widget=UnfoldAdminSelectWidget(),
        label="Сборщик",
    )

    class Meta:
        model = Assembly
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fields["user"].queryset = User.objects.filter(Q(user_permissions__codename=ASSEMBLY_PERMISSION) | Q(groups__permissions__codename=ASSEMBLY_PERMISSION)).values_list('id', 'name')
