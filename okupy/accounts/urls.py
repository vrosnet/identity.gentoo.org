# vim:fileencoding=utf8:et:ts=4:sts=4:sw=4:ft=python
from django.conf.urls import patterns, url

from .views import login, logout, index, signup, activate, formerdevlist, foundationlist

accounts_urlpatterns = patterns('',
    url(r'^$', index),
    url(r'^login/$', login),
    url(r'^logout/$', logout),
    url(r'^former-devlist/$', formerdevlist),
    url(r'^foundation-members/$', foundationlist),
    url(r'^signup/$', signup),
    url(r'^activate/(?P<token>[a-zA-Z0-9]+)/$', activate),
)