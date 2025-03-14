from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from backend.models import ConfirmEmailToken, User


@shared_task(name="new_user_registered")
def new_user_registered(user_id):
    """
    Отправляем письмо с подтверждением почты
    """
    token, _ = ConfirmEmailToken.objects.get_or_create(user_id=user_id)

    msg = EmailMultiAlternatives(
        # title:
        f"Password Reset Token for {token.user.email}",
        # message:
        token.key,
        # from:
        settings.EMAIL_HOST_USER,
        # to:
        [token.user.email]
    )
    msg.send()


@shared_task(name="new_order")
def new_order(user_id):
    """
    Отправляем письмо при изменении статуса заказа
    """
    user = User.objects.get(id=user_id)

    msg = EmailMultiAlternatives(
        # title:
        f"Обновление статуса заказа",
        # message:
        'Заказ сформирован',
        # from:
        settings.EMAIL_HOST_USER,
        # to:
        [user.email]
    )
    msg.send()