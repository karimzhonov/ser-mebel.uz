from telegram_webapp_auth.auth import TelegramAuthenticator, generate_secret_key
from telegram_webapp_auth.errors import InvalidInitDataError
from django.shortcuts import render
from django.contrib.auth import login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib.auth import get_user_model
from django.conf import settings

User = get_user_model()


def check_telegram_auth(auth_cred: str) -> bool:
    """
    Проверяет подпись initData от Telegram
    """
    bot_token = settings.TELEGRAM_BOT_TOKEN
    secret = generate_secret_key(bot_token)
    telegram_authenticator = TelegramAuthenticator(secret)
    try:
        return telegram_authenticator.validate(auth_cred)
    except InvalidInitDataError:
        raise InvalidInitDataError("Missing hash")


def telegram_admin_login(request):
    # initData может приходить как GET-параметры
    init_data = request.POST.get('initData')
    if not init_data:
        return render(request, 'oauth/twa.html')
    init_data = check_telegram_auth(init_data)
    telegram_id = init_data.user.id
    if not telegram_id:
        return HttpResponseForbidden("Telegram ID not found")

    try:
        user = User.objects.get(telegram_id=telegram_id)
    except User.DoesNotExist:
        return HttpResponseForbidden("User not allowed")

    # Логиним
    login(request, user)

    return redirect("/admin/")
