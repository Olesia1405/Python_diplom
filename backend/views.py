from django.contrib.auth import authenticate
from django.db import IntegrityError
from django.db.models import Q, Sum, F
from django.shortcuts import render

from rest_framework import viewsets, generics,  status
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.http import JsonResponse
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from requests import get
from yaml import load as load_yaml, Loader
from django.contrib.auth.password_validation import validate_password
from rest_framework.response import Response

from backend.models import Shop, Category, Product, ProductInfo, Parameter, ProductParameter, Order, OrderItem, \
    Contact, ConfirmEmailToken, User
from backend.serializers import UserSerializer, CategorySerializer, ShopSerializer, ProductInfoSerializer, \
    OrderItemSerializer, OrderSerializer, ContactSerializer
from backend.tasks import new_user_registered, new_order

from drf_spectacular.utils import extend_schema

import rollbar
from cachalot.decorators import cachalot



def str_to_bool(value):
    """Convert a string representation of truth to a boolean value."""
    return str(value).lower() in ("true", "t", "yes", "y", "1")


class RegisterAccount(APIView):
    """Для регистрации покупателей """
    throttle_scope = 'register'

    def post(self, request, *args, **kwargs):
        """Метод post проверяет наличие обязательных полей,
                и сохраняет пользователя в системе."""

        # проверяем обязательные аргументы
        if {'first_name', 'last_name', 'email', 'password', 'company', 'position'}.issubset(self.request.data):
            errors = {}
            # проверяем пароль на сложность
            try:
                validate_password(request.data['password'])
            except Exception as password_error:
                error_array = []
                # noinspection PyTypeChecker
                for item in password_error:
                    error_array.append(item)
                return Response({'Status': False, 'Errors': {'password': error_array}},
                                status=status.HTTP_403_FORBIDDEN)
            else:
                # проверяем данные для уникальности имени пользователя
                request.POST._mutable = True
                request.data.update({})
                user_serializer = UserSerializer(data=request.data)
                if user_serializer.is_valid():
                    # сохраняем пользователя
                    user = user_serializer.save()
                    user.set_password(request.data['password'])
                    user.save()
                    # new_user_registered.send(sender=self.__class__, user_id=user.id)
                    new_user_registered.delay(user_id=user.id)

                    return Response({'Status': True}, status=status.HTTP_201_CREATED)
                else:
                    return Response({'Status': False, 'Errors': user_serializer.errors},
                                    status=status.HTTP_403_FORBIDDEN)

        return Response({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                        status=status.HTTP_400_BAD_REQUEST)


class ConfirmAccount(APIView):
    """Класс для подтверждения почтового адреса"""

    throttle_scope = 'anon'

    def post(self, request, *args, **kwargs):
        """Метод post проверяет наличие обязательных полей
           и подтверждает пользователя в системе."""

        # проверяем обязательные аргументы и подтверждает пользователя в системе.
        if {'email', 'token'}.issubset(request.data):
            token = ConfirmEmailToken.objects.filter(user__email=request.data['email'],
                                                     key=request.data['token']).first()
            if token:
                token.user.is_active = True
                token.user.save()
                token.delete()
                return JsonResponse({'Status': True})
            else:
                return JsonResponse({'Status': False, 'Errors': 'Неправильно указан токен или email'})

        return Response({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                        status=status.HTTP_400_BAD_REQUEST)


class AccountDetails(generics.ListAPIView):
    """ Класс для работы данными пользователя """

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Метод get_queryset возвращает подробную информацию о пользователе."""

        user = User.objects.filter(id=self.request.user.id)
        return user


class LoginAccount(APIView):
    """Класс для авторизации пользователей"""

    # Авторизация методом POST
    def post(self, request, *args, **kwargs):
        """Метод post проверяет наличие обязательных полей и создает token пользователю."""

        throttle_scope = 'anon'

        if {'email', 'password'}.issubset(request.data):
            user = authenticate(username=request.data['email'], password=request.data['password'])

            if user is not None:
                if user.is_active:
                    token, _ = Token.objects.get_or_create(user=user)

                    return Response({'Status': True, 'Token': token.key})

            return Response({'Status': False, 'Errors': 'Не удалось авторизовать'},
                            status=status.HTTP_403_FORBIDDEN)

        return Response({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                        status=status.HTTP_400_BAD_REQUEST)



class CategoryView(ListAPIView):
    """ Класс для просмотра категорий"""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    @extend_schema(
        request=CategorySerializer,
        responses={200: CategorySerializer},
    )
    def get(self, request):
        """ Метод get возвращает список категорий. """

        return super().get(request)


class ShopView(ListAPIView):
    """ Класс для просмотра списка магазинов """

    queryset = Shop.objects.filter(state=True)
    serializer_class = ShopSerializer


class ProductInfoViewSet(viewsets.ReadOnlyModelViewSet):
    """ Класс для поиска товаров. """

    throttle_scope = 'anon'
    serializer_class = ProductInfoSerializer
    permission_classes = [IsAuthenticated]
    ordering = ('product')

    @extend_schema(
        request=ProductInfoSerializer,
        responses={200: ProductInfoSerializer},
    )


    def get_queryset(self):
        """Метод get_queryset принимает критерии для поиска,
        возвращает товары, в соотвествии с запросом. """

        query = Q(shop__state=True)
        shop_id = self.request.query_params.get('shop_id')
        category_id = self.request.query_params.get('category_id')

        if shop_id:
            query = query & Q(shop_id=shop_id)

        if category_id:
            query = query & Q(product__category_id=category_id)

        # фильтруем и отбрасываем дуликаты
        queryset = ProductInfo.objects.filter(
            query).select_related(
            'shop', 'product__category').prefetch_related(
            'product_parameters__parameter').distinct()

        return queryset


class BasketView(APIView):
    """Класс для работы с корзиной пользователя"""

    throttle_scope = 'user'

    def get(self, request, *args, **kwargs):
        """Метод get проверяет наличие авторизации пользователя
                и возвращает информацию о товарах в корзине."""

        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'},
                                status=status.HTTP_403_FORBIDDEN)
        basket = Order.objects.filter(
            user_id=request.user.id, state='basket').prefetch_related(
            'ordered_items__product_info__product__category',
            'ordered_items__product_info__product_parameters__parameter').annotate(
            total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()

        serializer = OrderSerializer(basket, many=True)
        return Response(serializer.data)

    # редактировать корзину
    def post(self, request, *args, **kwargs):
        """Метод post проверяет наличие авторизации пользователя,
           создает корзину для пользователя,
           размещая в ней необходимые товары и их количество."""

        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'},
                                status=status.HTTP_403_FORBIDDEN)

        items_sting = request.data.get('items')
        if items_sting:
            try:
                items_dict = items_sting
            except ValueError:
                Response({'Status': False, 'Errors': 'Неверный формат запроса'})
            else:
                basket, _ = Order.objects.get_or_create(user_id=request.user.id, state='basket')
                objects_created = 0
                for order_item in items_dict:
                    order_item.update({'order': basket.id})
                    serializer = OrderItemSerializer(data=order_item)
                    if serializer.is_valid(raise_exception=True):
                        try:
                            serializer.save()
                        except IntegrityError as error:
                            return Response({'Status': False, 'Errors': str(error)})
                        else:
                            objects_created += 1

                    else:

                        Response({'Status': False, 'Errors': serializer.errors})

                return Response({'Status': True, 'Создано объектов': objects_created},
                                status=status.HTTP_201_CREATED)
        return Response({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                        status=status.HTTP_400_BAD_REQUEST)

    # добавить позиции в корзину
    def put(self, request, *args, **kwargs):
        """Метод put проверяет наличие авторизации пользователя, обновляет данные заказа."""

        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'},
                                status=status.HTTP_403_FORBIDDEN)

        items_sting = request.data.get('items')
        if items_sting:
            try:
                items_dict = items_sting
            except ValueError:
                JsonResponse({'Status': False, 'Errors': 'Неверный формат запроса'})
            else:
                basket, _ = Order.objects.get_or_create(user_id=request.user.id, state='basket')
                objects_updated = 0
                for order_item in items_dict:
                    if type(order_item['product_info_id']) == int and type(order_item['quantity']) == int:
                        objects_updated += OrderItem.objects.filter(
                            order_id=basket.id,
                            product_info_id=order_item['product_info_id']).update(
                            quantity=order_item['quantity'])

                return JsonResponse({'Status': True, 'Обновлено объектов': objects_updated})
        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                            status=status.HTTP_400_BAD_REQUEST)

    # удалить товары из корзины
    def delete(self, request, *args, **kwargs):
        """Метод delete проверяет наличие авторизации, удаляет товары из корзины."""

        if not request.user.is_authenticated:
            return Response({'Status': False, 'Error': 'Log in required'}, status=status.HTTP_403_FORBIDDEN)

        items_sting = request.data.get('items')
        if items_sting:
            items_list = items_sting.split(',')
            basket, _ = Order.objects.get_or_create(user_id=request.user.id, state='basket')
            query = Q()
            objects_deleted = False
            for order_item_id in items_list:
                if order_item_id.isdigit():
                    query = query | Q(order_id=basket.id, id=order_item_id)
                    objects_deleted = True

            if objects_deleted:
                deleted_count = OrderItem.objects.filter(query).delete()[0]
                return Response({'Status': True, 'Удалено объектов': deleted_count})
        return Response({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                        status=status.HTTP_400_BAD_REQUEST)


class PartnerUpdate(APIView):
    """Класс для обновления прайса от поставщика"""

    throttle_scope = 'user'


    def post(self, request, *args, **kwargs):
        """Метод post проверяет наличие авторизации, проверяет,
           что покупатель имеет тип shop, формирует актуальный каталог. """

        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'},
                                status=status.HTTP_403_FORBIDDEN)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'},
                                status=status.HTTP_403_FORBIDDEN)

        url = request.data.get('url')
        if url:
            validate_url = URLValidator()
            try:
                validate_url(url)
            except ValidationError as e:
                return JsonResponse({'Status': False, 'Error': str(e)})
            else:
                stream = get(url).content
                data = load_yaml(stream, Loader=Loader)
                shop, _ = Shop.objects.get_or_create(name=data['shop'], user_id=request.user.id)
                for category in data['categories']:
                    category_object, _ = Category.objects.get_or_create(id=category['id'], name=category['name'])
                    category_object.shops.add(shop.id)
                    category_object.save()
                ProductInfo.objects.filter(shop_id=shop.id).delete()
                for item in data['goods']:
                    product, _ = Product.objects.get_or_create(name=item['name'], category_id=item['category'])

                    product_info = ProductInfo.objects.create(product_id=product.id,
                                                              external_id=item['id'],
                                                              model=item['model'],
                                                              price=item['price'],
                                                              price_rrc=item['price_rrc'],
                                                              quantity=item['quantity'],
                                                              shop_id=shop.id)
                    for name, value in item['parameters'].items():
                        parameter_object, _ = Parameter.objects.get_or_create(name=name)
                        ProductParameter.objects.create(product_info_id=product_info.id,
                                                        parameter_id=parameter_object.id,
                                                        value=value)

                return JsonResponse({'Status': True})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                            status=status.HTTP_403_FORBIDDEN)


class PartnerState(APIView):
    """Класс для работы со статусом поставщика"""

    def get(self, request, *args, **kwargs):
        """Метод get проверяет наличие авторизации,
           проверяет, что покупатель имеет тип shop,
           возвращает информацию о магазине и его статусе."""

        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'},
                                status=status.HTTP_403_FORBIDDEN)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'},
                                status=status.HTTP_403_FORBIDDEN)

        shop = request.user.shop
        serializer = ShopSerializer(shop)
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        """Метод get проверяет наличие авторизации,
           проверяет, что покупатель имеет тип shop,
           обновляет статус магазина."""

        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'},
                                status=status.HTTP_403_FORBIDDEN)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'},
                                status=status.HTTP_403_FORBIDDEN)
        state = request.data.get('state')
        if state:
            try:
                Shop.objects.filter(user_id=request.user.id).update(state=str_to_bool(state))
                return JsonResponse({'Status': True})
            except ValueError as error:
                return JsonResponse({'Status': False, 'Errors': str(error)},
                                    status=status.HTTP_400_BAD_REQUEST)

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                            status=status.HTTP_400_BAD_REQUEST)


class PartnerOrders(APIView):
    """Класс для получения заказов поставщиками """

    def get(self, request, *args, **kwargs):
        """Метод get проверяет наличие авторизации,
           проверяет, что покупатель имеет тип shop,
           получает заказ."""

        if not request.user.is_authenticated:
            return Response({'Status': False, 'Error': 'Log in required'},
                                status=status.HTTP_403_FORBIDDEN)

        if request.user.type != 'shop':
            return Response({'Status': False, 'Error': 'Только для магазинов'},
                                status=status.HTTP_403_FORBIDDEN)

        order = Order.objects.filter(
            ordered_items__product_info__shop__user_id=request.user.id).exclude(state='basket').prefetch_related(
            'ordered_items__product_info__product__category',
            'ordered_items__product_info__product_parameters__parameter').select_related('contact').annotate(
            total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()

        serializer = OrderSerializer(order, many=True)
        return Response(serializer.data)


class ContactView(APIView):
    """Класс для работы с контактами покупателей"""

    throttle_scope = 'user'

    def get(self, request, *args, **kwargs):
        """Метод get проверяет наличие авторизации,
           возвращает контактные данные покупателя."""

        if not request.user.is_authenticated:
            return Response({'Status': False, 'Error': 'Log in required'},
                                status=status.HTTP_403_FORBIDDEN)
        contact = Contact.objects.filter(user_id=request.user.id)
        serializer = ContactSerializer(contact, many=True)
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        """Метод post проверяет наличие авторизации,
           сохраняет контактные дынные покупателя."""

        if not request.user.is_authenticated:
            return Response({'Status': False, 'Error': 'Log in required'},
                            status=status.HTTP_403_FORBIDDEN)

        if {'city', 'street', 'phone'}.issubset(request.data):
            # request.data._mutable = True
            request.data.update({'user': request.user.id})
            serializer = ContactSerializer(data=request.data)

            if serializer.is_valid():
                serializer.save()
                return Response({'Status': True},
                                status=status.HTTP_201_CREATED)
            else:
                Response({'Status': False, 'Errors': serializer.errors})

        return Response({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                        status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, *args, **kwargs):
        """Метод put проверяет наличие авторизации,
           обновляет контактные дынные покупателя."""

        if not request.user.is_authenticated:
            return Response({'Status': False, 'Error': 'Log in required'},
                            status=status.HTTP_403_FORBIDDEN)

        if 'id' in request.data:
            if request.data['id'].isdigit():
                contact = Contact.objects.filter(id=request.data['id'], user_id=request.user.id).first()
                if contact:
                    serializer = ContactSerializer(contact, data=request.data, partial=True)
                    if serializer.is_valid():
                        serializer.save()
                        return Response({'Status': True})
                    else:
                        Response({'Status': False, 'Errors': serializer.errors})

        return Response({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                        status=status.HTTP_400_BAD_REQUEST)


    def delete(self, request, *args, **kwargs):
        """Метод delete проверяет наличие авторизации,
           удаляет контактные дынные покупателя."""
        if not request.user.is_authenticated:
            return Response({'Status': False, 'Error': 'Log in required'},
                            status=status.HTTP_403_FORBIDDEN)

        items_sting = request.data.get('items')
        if items_sting:
            items_list = items_sting.split(',')
            query = Q()
            objects_deleted = False
            for contact_id in items_list:
                if contact_id.isdigit():
                    query = query | Q(user_id=request.user.id, id=contact_id)
                    objects_deleted = True

            if objects_deleted:
                deleted_count = Contact.objects.filter(query).delete()[0]
                return Response({'Status': True, 'Удалено объектов': deleted_count})
        return Response({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                        status=status.HTTP_400_BAD_REQUEST)


class OrderView(APIView):
    """Класс для получения и размешения заказов пользователями"""

    throttle_scope = 'user'

    def get(self, request, *args, **kwargs):
        """Метод get проверяет наличие авторизации,
           возвращает заказы покупателя."""

        if not request.user.is_authenticated:
            return Response({'Status': False, 'Error': 'Log in required'},
                            status=status.HTTP_403_FORBIDDEN)

        order = Order.objects.filter(
            user_id=request.user.id).exclude(state='basket').prefetch_related(
            'ordered_items__product_info__product__category',
            'ordered_items__product_info__product_parameters__parameter').select_related('contact').annotate(
            total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()

        serializer = OrderSerializer(order, many=True)
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        """Метод get проверяет наличие авторизации,создает заказ."""

        if not request.user.is_authenticated:
            return Response({'Status': False, 'Error': 'Log in required'},
                            status=status.HTTP_403_FORBIDDEN)

        if {'id', 'contact'}.issubset(request.data):
            if request.data['id'].isdigit():
                try:
                    is_updated = Order.objects.filter(
                        user_id=request.user.id, id=request.data['id']).update(
                        contact_id=request.data['contact'],
                        state='new')
                except IntegrityError as error:
                    return Response({'Status': False, 'Errors': 'Неправильно указаны аргументы'},
                                    status=status.HTTP_400_BAD_REQUEST)
                else:
                    if is_updated:
                        print('1')
                        # new_order.send(sender=self.__class__, user_id=request.user.id)
                        new_order.delay(user_id=request.user.id)

                        return Response({'Status': True})

        return Response({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'},
                        status=status.HTTP_400_BAD_REQUEST)



class TestErrorView(APIView):
    def get(self, request, *args, **kwargs):
        try:
            # Вызов исключения для тестирования
            raise ValueError("Это тестовое исключение для проверки Rollbar")
        except ValueError as e:
            # Логирование исключения в Rollbar
            rollbar.report_exc_info()
            return Response({"status": "error", "message": str(e)}, status=500)

@cachalot(timeout=60 * 15)  # Кэшировать результат на 15 минут
def product_list(request):
    products = Product.objects.all()
    return render(request, 'product_list.html', {'products': products})