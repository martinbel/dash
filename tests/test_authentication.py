import time
import unittest
import dash
import plotly
import dash_html_components as html
from dash import authentication, plotly_api
import six
from six.moves import http_cookies
from six import iteritems

if six.PY3:
    from unittest import mock
else:
    import mock


# This is a real live access token associated with the
# test user `dash-test-user`.
# This token is generated by visiting
# https://plot.ly/o/authorize/?response_type=token&client_id=RcXzjux4DGfb8bWG9UNGpJUGsTaS0pUVHoEf7Ecl&redirect_uri=http://localhost:9595/oauth2/callback
# while logged in as that user and following the redirect
users = {
    'creator': {
        'username': 'dash-test-user',
        'oauth_token': 'SZO7wfzkQR43WjjqQpMDdtRnv2GsNN',
        'api_key': '9kCBELqYp54Dygjn7zhH'
    },
    'viewer': {
        'username': 'dash-test-viewer',
        'oauth_token': '8P1qbtfzMPJjqGGXPpnD4bN2f0wQvm'
    }
}


class ViewAccessTest(unittest.TestCase):
    def setUp(self):
        plotly.plotly.sign_in(
            users['creator']['username'],
            users['creator']['api_key']
        )
        self.fids = {}
        for permission in ['public', 'private', 'secret']:
            self.fids[permission] = plotly_api.create_or_overwrite_dash_app(
                'test-authentication-app-{}'.format(permission),
                permission,
                'http://localhost:9595'
            )

    def test_check_view_access(self):
        for user_type, user_attributes in iteritems(users):
            for permission, fid in iteritems(self.fids):
                if permission == 'public' or user_type == 'creator':
                    assertFunc = self.assertTrue
                else:
                    assertFunc = self.assertFalse
                has_access = authentication.check_view_access(
                    user_attributes['oauth_token'],
                    fid
                )
                test_name = '{} ({}) as {} ({}) is {}'.format(
                    permission, fid, user_type, user_attributes['oauth_token'],
                    has_access
                )
                assertFunc(has_access, test_name)


endpoints = {
    'protected': {
        'get': [
            '/layout', '/routes', '/dependencies',
        ],
        'post': ['/update-component']
    },
    'unprotected': {
        'get': [
            '/', '/_config', '/component-suites/dash-html-components'
        ],
        'post': [
            '/_login'
        ]
    }
}
n_protected_endpoints = len(endpoints['protected']['get'])


def get_cookie(res, cookie_name):
    headers = res.headers.to_list()
    cookie_string = [h for h in headers if (
        h[0] == 'Set-Cookie' and cookie_name in h[1]
    )][0][1]
    cookie = http_cookies.SimpleCookie(cookie_string)
    access_granted_cookie = cookie[list(cookie.keys())[0]].value
    return access_granted_cookie


class ProtectedViewsTest(unittest.TestCase):
    def setUp(self):
        plotly.plotly.sign_in(
            users['creator']['username'],
            users['creator']['api_key']
        )
        self.longMessage = True

    def create_apps(self):
        return {
            'unregistered': dash.Dash(),
            'public': dash.Dash(
                filename='public-app-test',
                sharing='public',
                app_url='http://localhost:5000'
            ),
            'private': dash.Dash(
                filename='private-app-test',
                sharing='private',
                app_url='http://localhost:5000'
            ),
            'secret': dash.Dash(
                filename='secret-app-test',
                sharing='secret',
                app_url='http://localhost:5000'
            )
        }

    def test_unauthenticated_view(self):
        apps = self.create_apps()
        for app in [apps['unregistered'], apps['public']]:
            app = dash.Dash()
            app.layout = html.Div()
            client = app.server.test_client()
            for endpoint in (endpoints['protected']['get'] +
                             endpoints['unprotected']['get']):
                res = client.get(endpoint)
                self.assertEqual(res.status_code, 200)

    def test_403_on_protected_endpoints_without_cookie(self):
        apps = self.create_apps()
        for app in [apps['private'], apps['secret']]:
            app.layout = html.Div()
            client = app.server.test_client()
            for endpoint in endpoints['unprotected']['get']:
                res = client.get(endpoint)
                self.assertEqual(res.status_code, 200, endpoint)
            for endpoint in endpoints['protected']['get']:
                res = client.get(endpoint)
                self.assertEqual(res.status_code, 403, endpoint)

            # TODO - check 200 on unprotected endpoints?
            for endpoint in endpoints['protected']['post']:
                res = client.post(endpoint)
                self.assertEqual(res.status_code, 403, endpoint)

    def check_endpoints(self, app, oauth_token, cookies=[], all_200=False):
        def get_client():
            client = app.server.test_client()
            client.set_cookie(
                '/',
                'plotly_oauth_token',
                oauth_token
            )
            for cookie in cookies:
                client.set_cookie('/', cookie['name'], cookie['value'])
            return client

        for endpoint in (endpoints['unprotected']['get'] +
                         endpoints['protected']['get']):
            client = get_client()  # use a fresh client for every endpoint
            res = client.get(endpoint)
            test_name = '{} at {} as {} on {}'.format(
                res.status_code, endpoint, oauth_token, app.fid
            )
            if (app.fid is None or
                    app.sharing == 'public' or
                    oauth_token == users['creator']['oauth_token'] or
                    endpoint in endpoints['unprotected']['get'] or
                    all_200):
                self.assertEqual(res.status_code, 200, test_name)
            elif app.sharing in ['private', 'secret']:
                self.assertEqual(res.status_code, 403, test_name)
        return res

    def test_protected_endpoints_with_auth_cookie(self):
        apps = self.create_apps()
        for user_type, user_attributes in iteritems(users):
            for app_name, app in iteritems(apps):
                app.layout = html.Div()
                self.check_endpoints(
                    app,
                    user_attributes['oauth_token'],
                )

    def test_permissions_can_change(self):
        fn = 'private-flip-flop-app-test'
        au = 'http://localhost:5000'
        app = dash.Dash(
            filename=fn,
            sharing='private',
            app_url=au
        )
        app.layout = html.Div()
        app.config.permissions_cache_expiry = 30
        app.create_access_codes()
        viewer = users['viewer']['oauth_token']

        creator = users['creator']['oauth_token']
        with mock.patch('dash.authentication.check_view_access',
                        wraps=authentication.check_view_access) as wrapped:
            # sanity check the endpoints when the app is private
            self.check_endpoints(app, viewer)
            self.assertEqual(wrapped.call_count, n_protected_endpoints)

            # make the app public
            plotly_api.create_or_overwrite_dash_app(fn, 'public', au)
            app.sharing = 'public'  # used in the check_endpoints assertions
            res = self.check_endpoints(app, viewer)
            self.assertEqual(wrapped.call_count, n_protected_endpoints * 2)

            # The last access granted response contained a cookie that grants
            # the user access for 30 seconds (5 minutes by default)
            # without making an API call to plotly.
            # Include this cookie in the response and verify that it grants
            # the user access up until the expiration date
            access_granted_cookie = get_cookie(res, 'dash_access')
            self.assertEqual(
                access_granted_cookie,
                app.access_codes['access_granted']
            )
            self.assertEqual(wrapped.call_count, n_protected_endpoints * 2)

            plotly_api.create_or_overwrite_dash_app(fn, 'private', au)
            app.sharing = 'private'  # used in the check_endpoints assertions
            # Even though the app is private, the viewer will still get 200s
            access_cookie = [
                {'name': app.auth_cookie_name, 'value': access_granted_cookie}
            ]
            self.check_endpoints(
                app, viewer, access_cookie, all_200=True
            )
            self.assertEqual(wrapped.call_count, n_protected_endpoints * 2)

            # But after 30 seconds, the auth token will expire,
            # and the user will be denied access
            time.sleep(5)
            self.check_endpoints(app, viewer, access_cookie, all_200=True)
            self.assertEqual(wrapped.call_count, n_protected_endpoints * 2)
            time.sleep(26)
            self.check_endpoints(app, viewer, access_cookie)
            self.assertEqual(wrapped.call_count, n_protected_endpoints * 3)

    def test_auth_cookie_caches_calls_to_plotly(self):
        app = dash.Dash(
            filename='private-cookie-test',
            sharing='private',
            app_url='http://localhost:5000'
        )
        app.layout = html.Div()

        creator = users['creator']['oauth_token']
        with mock.patch('dash.authentication.check_view_access',
                        wraps=authentication.check_view_access) as wrapped:
            self.check_endpoints(app, creator)
            res = self.check_endpoints(app, creator)
            self.assertEqual(wrapped.call_count, 2 * n_protected_endpoints)

            access_granted_cookie = get_cookie(res, 'dash_access')
            self.check_endpoints(app, creator, [
                {'name': app.auth_cookie_name, 'value': access_granted_cookie}
            ])
            self.assertEqual(wrapped.call_count, 2 * n_protected_endpoints)

            # Regenerate tokens with a shorter expiration
            # User's won't actually do this in practice, we're
            # just doing it to shorten up the expiration from 5 min
            # to 10 seconds
            app.config.permissions_cache_expiry = 10
            app.create_access_codes()
            res = self.check_endpoints(app, creator)
            self.assertEqual(wrapped.call_count, 3 * n_protected_endpoints)

            # Using the same auth cookie should prevent an
            # additional access call
            time.sleep(5)
            access_granted_cookie = get_cookie(res, 'dash_access')
            self.check_endpoints(app, creator, [
                {'name': app.auth_cookie_name, 'value': access_granted_cookie}
            ])
            self.assertEqual(wrapped.call_count, 3 * n_protected_endpoints)

            # But after the expiration time (10 seconds), another call to
            # plotly should be made
            time.sleep(6)
            res = self.check_endpoints(app, creator)
            self.assertEqual(wrapped.call_count, 4 * n_protected_endpoints)


class LoginFlow(unittest.TestCase):
    def login_success(self):
        app = dash.Dash()
        app.layout = html.Div()
        client = app.server.test_client()
        csrf_token = get_cookie(client.get('/'), '_csrf_token')
        client.set_cookie('/', '_csrf_token', csrf_token)
        oauth_token = users['creator']['oauth_token']
        res = client.post('_login', headers={
            'Authorization': 'Bearer {}'.format(oauth_token),
            'X-CSRFToken': csrf_token
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            get_cookie(res, 'plotly_oauth_token'),
            token
        )
