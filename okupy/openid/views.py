# vim:fileencoding=utf8:et:ts=4:sw=4:sts=4

import re
from urlparse import urljoin

from django.conf import settings
from django.contrib import auth
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
import django.contrib.auth.views as auth_views

# XXX: temporary solution
from openid.store.filestore import FileOpenIDStore
from openid.server.server import Server, ProtocolError, EncodingError, \
        CheckIDRequest

# for exceptions
import openid.yadis.discover, openid.fetchers

from .openid_store import DjangoDBOpenIDStore

def login(request):
    oreq = request.session.get('openid_request', None)
    if request.POST and 'cancel' in request.POST:
        if oreq is not None:
            oresp = oreq.answer(False)
            del request.session['openid_request']
            return render_openid_response(request, oresp)
        else:
            # cheat it to display the form again
            request.method = 'GET'

    f = AuthenticationForm
    # set initial data if appropriate.
    if isinstance(oreq, CheckIDRequest):
        ref_uri = request.build_absolute_uri(reverse(user_page, args=('USERNAME',)))
        ref_uri = re.compile(re.escape(ref_uri).replace('USERNAME', r'(\w+)'))
        m = ref_uri.match(oreq.identity)
        if m:
            class PreInitAuthForm(object):
                def __init__(self, username):
                    self.initial = {'username': username}

                def __call__(self, *args, **kwargs):
                    kwargs['initial'] = self.initial
                    return AuthenticationForm(*args, **kwargs)

            f = PreInitAuthForm(m.group(1))

    return auth_views.login(request,
            template_name = 'openid/login.html',
            authentication_form = f)

def logout(request):
    auth.logout(request)
    return redirect('openid.index')

def index(request):
    return render(request, 'openid/index.html')

def endpoint_url(request):
    return request.build_absolute_uri(reverse(endpoint))

def user_page(request, username):
    return render(request, 'openid/user.html',
            {
                'endpoint': endpoint_url(request),
            })

def render_openid_response(request, oresp, srv = None):
    if srv is None:
        store = DjangoDBOpenIDStore()
        srv = Server(store, endpoint_url(request))

    try:
        eresp = srv.encodeResponse(oresp)
    except EncodingError as e:
        # XXX: do we want some different heading for it?
        return render(request, 'openid/endpoint.html',
                {
                    'error': str(e)
                }, status = 500)

    dresp = HttpResponse(eresp.body, status = eresp.code)
    for h, v in eresp.headers.items():
        dresp[h] = v

    return dresp

@csrf_exempt
def endpoint(request):
    if request.method == 'POST':
        req = request.POST
    else:
        req = request.GET

    store = DjangoDBOpenIDStore()
    srv = Server(store, endpoint_url(request))

    try:
        oreq = srv.decodeRequest(req)
    except ProtocolError as e:
        # XXX: we are supposed to send some error to the caller
        return render(request, 'openid/endpoint.html',
                {
                    'error': str(e)
                }, status = 400)

    if oreq is None:
        return render(request, 'openid/endpoint.html')

    if isinstance(oreq, CheckIDRequest):
        # immediate requests not supported yet, so immediately
        # reject them.
        if oreq.immediate:
            oresp = oreq.answer(False)
        else:
            request.session['openid_request'] = oreq
            return redirect(auth_site)
    else:
        oresp = srv.handleRequest(oreq)

    return render_openid_response(request, oresp, srv)

@login_required
def auth_site(request):
    try:
        oreq = request.session['openid_request']
    except KeyError:
        return render(request, 'openid/auth-site.html',
                {
                    'error': 'No OpenID request associated. The request may have expired.'
                }, status = 400)

    if request.POST:
        if 'accept' in request.POST:
            oresp = oreq.answer(True,
                    identity=request.build_absolute_uri(reverse(user_page, args=(request.user.username,))))
        elif 'reject' in request.POST:
            oresp = oreq.answer(False)
        else:
            return render(request, 'openid/auth-site.html',
                    {
                        'error': 'Invalid request submitted.'
                    }, status = 400)

        del request.session['openid_request']
        return render_openid_response(request, oresp)

    if not oreq.trustRootValid():
        tr_valid = 'Return-To invalid (not under trust root)'
    else:
        try:
            # XXX: cache it
            if oreq.returnToVerified():
                tr_valid = 'Return-To valid and trusted'
            else:
                tr_valid = 'Return-To untrusted'
        except openid.yadis.discover.DiscoveryFailure:
            tr_valid = 'Unable to verify trust (Yadis unsupported)'
        except openid.fetchers.HTTPFetchingError:
            tr_valid = 'Unable to verify trust (HTTP error)'

    return render(request, 'openid/auth-site.html',
            {
                'request': oreq,
                'return_to_valid': tr_valid,
            })
