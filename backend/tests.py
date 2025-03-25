from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from backend.models import User, Category, Shop, ProductInfo, Order, Contact

class RegisterAccountTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('backend:user-register')
        self.user_data = {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john.doe@example.com',
            'password': 'StrongPassword123',
            'company': 'Test Company',
            'position': 'Developer'
        }

    def test_register_account(self):
        response = self.client.post(self.url, self.user_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data['Status'], True)

class ConfirmAccountTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('backend:user-register-confirm')
        self.user = User.objects.create_user(username='testuser', email='testuser@example.com', password='password')
        self.confirm_data = {
            'email': 'testuser@example.com',
            'token': 'valid-token'  # Замените на реальный токен
        }

    def test_confirm_account(self):
        response = self.client.post(self.url, self.confirm_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data['Status'], True)

class LoginAccountTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('backend:user-login')
        self.user = User.objects.create_user(username='testuser', email='testuser@example.com', password='password')
        self.login_data = {
            'email': 'testuser@example.com',
            'password': 'password'
        }

    def test_login_user(self):
        response = self.client.post(self.url, self.login_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue('Token' in response.json())

class CategoryViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('backend:categories')
        Category.objects.create(name='Test Category')

    def test_get_category_list(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

class ShopViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('backend:shops')
        Shop.objects.create(name='Test Shop', state=True)

    def test_get_shop_list(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

class ProductInfoViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('backend:products-list')
        self.shop = Shop.objects.create(name='Test Shop', state=True)
        self.category = Category.objects.create(name='Test Category')
        self.product = ProductInfo.objects.create(
            product_id=1,
            external_id=1,  # Убедитесь, что это значение уникально для каждого продукта
            model='Test Model',
            price=100,
            quantity=10,
            shop=self.shop
        )

    def test_get_product_list(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

class BasketViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('backend:basket')
        self.user = User.objects.create_user(username='testuser', email='testuser@example.com', password='password')
        self.client.force_authenticate(user=self.user)
        self.order = Order.objects.create(user=self.user, state='basket')

    def test_get_basket(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

class OrderViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('backend:order')
        self.user = User.objects.create_user(username='testuser', email='testuser@example.com', password='password')
        self.client.force_authenticate(user=self.user)
        self.order = Order.objects.create(user=self.user, state='new')

    def test_get_orders(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

class ContactViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('backend:user-contact')
        self.user = User.objects.create_user(username='testuser', email='testuser@example.com', password='password')
        self.client.force_authenticate(user=self.user)
        self.contact_data = {
            'city': 'Test City',
            'street': 'Test Street',
            'phone': '123456789'
        }

    def test_create_contact(self):
        response = self.client.post(self.url, self.contact_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_get_contact(self):
        Contact.objects.create(user=self.user, **self.contact_data)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
