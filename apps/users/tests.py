from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


class RegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.register_url = '/api/v1/auth/register/'

    def test_register_success(self):
        data = {
            'email': 'test@example.com',
            'username': 'testuser',
            'password': 'securepass123',
        }
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('user', response.data)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['user']['email'], 'test@example.com')

    def test_register_duplicate_email(self):
        User.objects.create_user(email='test@example.com', password='pass12345')
        data = {
            'email': 'test@example.com',
            'username': 'another',
            'password': 'securepass123',
        }
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_short_password(self):
        data = {
            'email': 'test@example.com',
            'password': 'short',
        }
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.login_url = '/api/v1/auth/login/'
        self.user = User.objects.create_user(
            email='test@example.com', password='securepass123'
        )

    def test_login_success(self):
        data = {'email': 'test@example.com', 'password': 'securepass123'}
        response = self.client.post(self.login_url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_wrong_password(self):
        data = {'email': 'test@example.com', 'password': 'wrongpassword'}
        response = self.client.post(self.login_url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_nonexistent_user(self):
        data = {'email': 'nobody@example.com', 'password': 'pass12345'}
        response = self.client.post(self.login_url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class BootstrapTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.bootstrap_url = '/api/v1/auth/bootstrap/'

    def test_bootstrap_creates_install_identity(self):
        response = self.client.post(self.bootstrap_url, {
            'installation_id': 'b' * 36,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertTrue(response.data['user']['email'].endswith('@orbit.local'))
        self.assertFalse(response.data['user']['email'].startswith('b' * 36))

    def test_bootstrap_is_idempotent_for_same_install_id(self):
        first = self.client.post(self.bootstrap_url, {
            'installation_id': 'c' * 36,
        })
        second = self.client.post(self.bootstrap_url, {
            'installation_id': 'c' * 36,
        })
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data['user']['id'], second.data['user']['id'])
        self.assertNotEqual(first.data['access'], second.data['access'])

    def test_bootstrap_different_install_ids_get_different_users(self):
        first = self.client.post(self.bootstrap_url, {
            'installation_id': 'd' * 36,
        })
        second = self.client.post(self.bootstrap_url, {
            'installation_id': 'e' * 36,
        })
        self.assertNotEqual(first.data['user']['id'], second.data['user']['id'])

    def test_bootstrap_rejects_short_install_id(self):
        response = self.client.post(self.bootstrap_url, {
            'installation_id': 'short',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bootstrap_rejects_missing_install_id(self):
        response = self.client.post(self.bootstrap_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bootstrap_tokens_work_for_authenticated_endpoints(self):
        response = self.client.post(self.bootstrap_url, {
            'installation_id': 'f' * 36,
        })
        access = response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        me = self.client.get('/api/v1/auth/me/')
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data['id'], response.data['user']['id'])
