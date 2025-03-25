from django.contrib.auth.models import User

def save_profile_picture(backend, user, response, *args, **kwargs):
    if backend.name == 'yandex-oauth2':
        avatar_url = response.get('default_avatar_id')
        if avatar_url:
            # Сохраните URL фото профиля в модели пользователя или другой модели
            user.profile.avatar_url = avatar_url
            user.profile.save()
