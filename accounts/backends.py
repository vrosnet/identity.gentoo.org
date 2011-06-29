from django.conf import settings
from django.contrib.auth.models import User
from okupy.accounts.models import *
from okupy.libraries.ldap_wrappers import *
from okupy.libraries.exception import OkupyException, log_extra_data
import ldap
import logging

logger = logging.getLogger('okupy')

class LDAPBackend(object):
    '''
    LDAP authentication backend
    '''
    def authenticate(self, mail = None, password = None):
        '''
        Try to authenticate the user. If there isn't such user
        in the Django DB, and assuming the credentials are correct,
        the user's data will be migrated from the LDAP server
        to the Django DB.
        '''
        if not password:
            return None
        return self.get_or_create_user(mail, password)


    def get_user(self, user_id):
        '''
        Retrieve a specific user from the Django DB
        '''
        try:
            return User.objects.get(pk = user_id)
        except User.DoesNotExist:
            return None

    def get_or_create_user(self, mail, password, other_username = None, other_password = None):
        '''
        Retrieves a user from the Django DB. If the user is not
        found in the DB, then it tries to retrieve it from the
        LDAP server. It needs the ability to perform an anonymous
        query, or a minimal privileged user (LDAP_ANON_USER_{DN,PW})
        should do it instead. If the user is found, the data are
        then moved to the Django DB.
        '''
        try:
            user = User.objects.get(gentooprofile__all_mails__contains = mail)
        except (User.DoesNotExist, ValueError):
            '''
            Perform a search to find the user in the LDAP server.
            '''
            results = ldap_user_search(mail, 'mail')
            if not results:
                return None
            '''
            In case there is a result available, it means
            that the user is in the LDAP server. Next step
            is to try to bind to the LDAP server using the
            user's credentials, to check if they are valid.
            Since this method is used for privileged users
            to retrieve other users' data, other is defined,
            then it doesn't need to bind.
            '''
            username = results[0][1]['uid'][0]
            original_username = username
            if other_username:
                username = other_username
                password = other_password
            l_user = None
            for ldap_base_dn in settings.LDAP_BASE_DN:
                try:
                    l_user = ldap_bind(username, password,
                                settings.LDAP_BASE_ATTR,
                                ldap_base_dn)
                    '''
                    Again, we need to search in multiple OU's for
                    the user's existence.
                    '''
                    if l_user:
                        break
                except:
                    pass
            if not l_user:
                return None
            '''
            Perform another search as the current user, to get
            all his data
            '''
            results = ldap_user_search(original_username, anon = False, l = l_user)
            '''
            In case everything went fine so far, it means there is
            a valid user available. Last step is to migrate the user's
            data to the Django DB.
            '''
            user = User()
            for field, attr in settings.LDAP_USER_ATTR_MAP.iteritems():
                try:
                    setattr(user, field, results[0][1][attr][0])
                except Exception as error:
                    logger.error(error, extra = log_extra_data())
                    raise OkupyException('LDAP User Attribute Map is invalid')
            user.set_unusable_password()
            '''
            Additional data that should be put in the user's profile
            '''
            try:
                if settings.LDAP_PROFILE_ATTR_MAP:
                    user_profile = eval(settings.AUTH_PROFILE_MODULE.split('accounts.')[1] + '()')
                    for field, attr in settings.LDAP_PROFILE_ATTR_MAP.iteritems():
                        try:
                            setattr(user_profile, field, '::'.join(results[0][1][attr]))
                        except Exception as error:
                            logger.error(error, extra = log_extra_data())
                            raise OkupyException('LDAP Profile Attribute Map is invalid')
                    '''
                    Check if the user is member of the groups under
                    settings.LDAP_ACL_GROUPS. In order to do this, the
                    system compares the contents of that list with the
                    values of the LDAP attribute settings.LDAP_ACL_ATTR.
                    For correct results, it sets the according is_field
                    of the UserProfile to True.
                    '''
                    for field, attr in settings.LDAP_ACL_GROUPS.iteritems():
                        if field in results[0][1][settings.LDAP_ACL_ATTR]:
                            try:
                                setattr(user_profile, attr, True)
                            except Exception as error:
                                logger.error(error, extra = log_extra_data())
                                raise OkupyException('LDAP ACL Groups Map is invalid')
            except AttributeError:
                pass
            '''
            Save data in DB
            '''
            try:
                user.save()
                user_profile.user = user
                user_profile.save()
            except Exception as error:
                logger.error(error, extra = log_extra_data())
                raise OkupyException('Could not save to DB')
        return user
