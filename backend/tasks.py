from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from easy_thumbnails.files import get_thumbnailer
from django.core.files.storage import default_storage
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

@shared_task
def generate_thumbnails(image_path, sizes):
    thumbnailer = get_thumbnailer(default_storage.open(image_path))
    for alias, size in sizes.items():
        thumbnail = thumbnailer.get_thumbnail({
            'size': size,
            'crop': True,
        })
        thumbnail_path = f"{image_path}_{alias}.jpg"
        with default_storage.open(thumbnail_path, 'wb') as f:
            thumbnail.save(f)