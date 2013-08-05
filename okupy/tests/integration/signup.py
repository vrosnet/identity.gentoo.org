# vim:fileencoding=utf8:et:ts=4:sts=4:sw=4:ft=python

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.db import DatabaseError
from django.test.client import Client
from mockldap import MockLdap

from ...accounts.models import Queue
from ...common.testcase import OkupyTestCase

import mock

class SignupTestsEmptyDB(OkupyTestCase):
    form_data = {
        'username': 'testusername',
        'first_name': 'testfirstname',
        'last_name': 'testlastname',
        'email': 'test@test.com',
        'password_origin': 'testpassword',
        'password_verify': 'testpassword',
    }

    def setUp(self):
        self.client = Client()

    def test_template(self):
        response = self.client.get('/signup/')
        self.assertIn('signup_form', response.context)
        self.assertIn('messages', response.context)

    def test_empty_form(self):
        response = self.client.post('/signup/')
        self.assertFormError(response, 'signup_form', 'username', [u'This field is required.'])
        self.assertFormError(response, 'signup_form', 'first_name', [u'This field is required.'])
        self.assertFormError(response, 'signup_form', 'last_name', [u'This field is required.'])
        self.assertFormError(response, 'signup_form', 'email', [u'This field is required.'])
        self.assertFormError(response, 'signup_form', 'password_origin', [u'This field is required.'])
        self.assertFormError(response, 'signup_form', 'password_verify', [u'This field is required.'])
        self.assertEqual(Queue.objects.count(), 0)

    def test_passwords_dont_match(self):
        form_data = self.form_data.copy()
        form_data['password_verify'] = 'testpassword2'
        response = self.client.post('/signup/', form_data)
        self.assertMessage(response, "Passwords don't match", 40)
        self.assertEqual(Queue.objects.count(), 0)

    def test_invalid_email(self):
        form_data = self.form_data.copy()
        form_data['email'] = 'test'
        response = self.client.post('/signup/', form_data)
        self.assertFormError(response, 'signup_form', 'email', [u'Enter a valid email address.'])
        self.assertEqual(Queue.objects.count(), 0)

class SignupTestsOneAccountInQueue(OkupyTestCase):
    fixtures = ['queued_account.json']

    cursor_wrapper = mock.Mock()
    cursor_wrapper.side_effect = DatabaseError

    form_data = {
        'username': 'testusername',
        'first_name': 'testfirstname',
        'last_name': 'testlastname',
        'email': 'test@test.com',
        'password_origin': 'testpassword',
        'password_verify': 'testpassword',
    }

    @classmethod
    def setUpClass(cls):
        cls.mockldap = MockLdap(settings.DIRECTORY)

    def setUp(self):
        self.client = Client()
        self.queued_account = Queue.objects.get(pk=1)
        self.activate_url = '/activate/%s/' % self.queued_account.encrypted_id
        self.mockldap.start()
        self.ldapobject = self.mockldap[settings.AUTH_LDAP_SERVER_URI]

    def tearDown(self):
        self.mockldap.stop()

    def test_add_queued_account_to_ldap(self):
        response = self.client.get(self.activate_url)
        self.assertRedirects(response, '/login/')
        self.assertMessage(response, 'Your account has been activated successfully', 25)
        self.assertEqual(Queue.objects.count(), 0)
        ldap_account = self.ldapobject.directory['uid=%s,ou=people,o=test' % self.queued_account.username]
        self.assertEqual(ldap_account['uid'][0], self.queued_account.username)
        self.assertEqual(ldap_account['givenName'][0], self.queued_account.first_name)
        self.assertEqual(ldap_account['sn'][0], self.queued_account.last_name)
        self.assertEqual(ldap_account['objectClass'], settings.AUTH_LDAP_USER_OBJECTCLASS)
        self.assertEqual(ldap_account['uidNumber'][0], '1002')
        self.assertEqual(ldap_account['mail'][0], self.queued_account.email)
        data = {'username': self.queued_account.username, 'password': 'queuedpass'}
        response = self.client.post('/login/', data)
        self.assertRedirects(response, '/')
        self.assertEqual(User.objects.count(), 1)
        response = self.client.get(self.activate_url)
        self.assertMessage(response, 'Invalid URL', 40)

    def test_signup_no_ldap(self):
        self.mockldap.stop()
        response = self.client.post('/signup/', self.form_data)
        self.assertMessage(response, "Can't contact LDAP server", 40)
        self.assertEqual(Queue.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, '%sERROR: {\'desc\': "Can\'t contact LDAP server"}' % settings.EMAIL_SUBJECT_PREFIX)
        self.mockldap.start()

    def test_activate_no_ldap(self):
        self.mockldap.stop()
        response = self.client.get(self.activate_url)
        self.assertRedirects(response, '/login/')
        self.assertMessage(response, "Can't contact LDAP server", 40)
        self.assertEqual(Queue.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, '%sERROR: {\'desc\': "Can\'t contact LDAP server"}' % settings.EMAIL_SUBJECT_PREFIX)
        self.mockldap.start()

    def test_wrong_activation_link(self):
        response = self.client.get('/activate/invalidurl/')
        self.assertRedirects(response, '/login/')
        self.assertMessage(response, 'Invalid URL', 40)
        self.assertEqual(Queue.objects.count(), 1)

    def test_username_already_exists_in_ldap(self):
        form_data = self.form_data.copy()
        form_data['username'] = 'alice'
        response = self.client.post('/signup/', form_data)
        self.assertMessage(response, 'Username already exists', 40)

    def test_email_already_exists_in_ldap(self):
        form_data = self.form_data.copy()
        form_data['email'] = 'alice@test.com'
        response = self.client.post('/signup/', form_data)
        self.assertMessage(response, 'Email already exists', 40)

    def test_username_already_pending_activation(self):
        form_data = self.form_data.copy()
        form_data['username'] = 'queueduser'
        response = self.client.post('/signup/', form_data)
        self.assertMessage(response, 'Account is already pending activation', 40)
        self.assertEqual(Queue.objects.count(), 1)

    def test_email_already_pending_activation(self):
        form_data = self.form_data.copy()
        form_data['email'] = 'queueduser@test.com'
        response = self.client.post('/signup/', form_data)
        self.assertMessage(response, 'Account is already pending activation', 40)
        self.assertEqual(Queue.objects.count(), 1)

    def test_valid_data_to_form(self):
        response = self.client.post('/signup/', self.form_data)
        self.assertRedirects(response, '/login/')
        self.assertMessage(response, 'You will shortly receive an activation mail', 20)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, '%sAccount Activation' % settings.EMAIL_SUBJECT_PREFIX)
        self.assertEqual(Queue.objects.count(), 2)
        queued_account = Queue.objects.get(pk=2)
        self.assertEqual(queued_account.username, self.form_data['username'])
        self.assertEqual(queued_account.first_name, self.form_data['first_name'])
        self.assertEqual(queued_account.last_name, self.form_data['last_name'])
        self.assertEqual(queued_account.email, self.form_data['email'])
        self.assertEqual(queued_account.password, self.form_data['password_origin'])
        self.assertRegexpMatches(queued_account.encrypted_id, '^[a-f0-9]{32}$')

    @mock.patch("django.db.backends.util.CursorWrapper", cursor_wrapper)
    def test_signup_no_database(self):
        response = self.client.post('/signup/', self.form_data)
        self.assertMessage(response, "Can't contact the database", 40)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].subject.startswith('%sERROR:' % settings.EMAIL_SUBJECT_PREFIX))

    @mock.patch("django.db.backends.util.CursorWrapper", cursor_wrapper)
    def test_activate_no_database(self):
        response = self.client.post(self.activate_url)
        self.assertMessage(response, "Can't contact the database", 40)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].subject.startswith('%sERROR:' % settings.EMAIL_SUBJECT_PREFIX))

    def test_add_first_user_empty_ldap_directory(self):
        self.ldapobject.directory = {}
        response = self.client.post(self.activate_url)
        self.assertRedirects(response, '/login/')
        self.assertMessage(response, 'Your account has been activated successfully', 25)
        self.assertEqual(Queue.objects.count(), 0)
        ldap_account = self.ldapobject.directory['uid=%s,ou=people,o=test' % self.queued_account.username]
        self.assertEqual(ldap_account['uid'][0], self.queued_account.username)
        self.assertEqual(ldap_account['givenName'][0], self.queued_account.first_name)
        self.assertEqual(ldap_account['sn'][0], self.queued_account.last_name)
        self.assertEqual(ldap_account['objectClass'], settings.AUTH_LDAP_USER_OBJECTCLASS)
        self.assertEqual(ldap_account['uidNumber'][0], '1')
        self.assertEqual(ldap_account['mail'][0], self.queued_account.email)
        data={'username': self.queued_account.username, 'password': 'queuedpass'}
        response = self.client.post('/login/', data)
        self.assertRedirects(response, '/')
        self.assertEqual(User.objects.count(), 1)
        response = self.client.get(self.activate_url)
        self.assertMessage(response, 'Invalid URL', 40)
