from django.contrib.auth.models import Group
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from core.telegram import bot_link
from oauth.models import User


class MeSerializer(serializers.ModelSerializer):
    phone = PhoneNumberField(region="UZ", read_only=True)
    permissions = serializers.SerializerMethodField()
    telegram_link = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "name",
            "telegram_id",
            "is_superuser",
            "permissions",
            "telegram_link",
        ]
        read_only_fields = fields

    def get_permissions(self, obj):
        return sorted(obj.get_all_permissions())

    def get_telegram_link(self, obj):
        # Same deep link as the admin's "Связать Telegram" menu item; the bot's
        # /start handler writes telegram_id for this user id.
        return bot_link(obj.pk)


class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ["id", "name"]


class UserSerializer(serializers.ModelSerializer):
    """Superuser-only staff management. Fine-grained permissions stay in the Django
    admin; here a user is given groups."""

    phone = PhoneNumberField(region="UZ")
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, min_length=6
    )
    groups = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.all(), many=True, required=False
    )

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "name",
            "telegram_id",
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "last_login",
            "password",
        ]
        read_only_fields = ["telegram_id", "is_superuser", "last_login"]

    def create(self, validated_data):
        groups = validated_data.pop("groups", [])
        password = validated_data.pop("password", None) or None
        user = User.objects.create_user(password=password, **validated_data)
        if password is None:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        user.groups.set(groups)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user
