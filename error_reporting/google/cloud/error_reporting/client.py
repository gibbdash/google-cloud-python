# Copyright 2016 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Client for interacting with the Stackdriver Error Reporting API"""

import os
import traceback

try:
    from google.cloud.error_reporting._gax import make_report_error_api
    _HAVE_GAX = True
except ImportError:  # pragma: NO COVER
    _HAVE_GAX = False

from google.cloud._helpers import _determine_default_project
from google.cloud.error_reporting._logging import _ErrorReportingLoggingAPI
from google.cloud.environment_vars import DISABLE_GRPC

import six

_DISABLE_GAX = os.getenv(DISABLE_GRPC, False)
_USE_GAX = _HAVE_GAX and not _DISABLE_GAX


class HTTPContext(object):
    """HTTPContext defines an object that captures the parameter for the
    httpRequest part of Error Reporting API

    :type method: str
    :param method: The type of HTTP request, such as GET, POST, etc.

    :type url: str
    :param url: The URL of the request

    :type user_agent: str
    :param user_agent: The user agent information that is provided with the
                       request.

    :type referrer: str
    :param referrer: The referrer information that is provided with the
                     request.

    :type response_status_code: int
    :param response_status_code: The HTTP response status code for the request.

    :type remote_ip: str
    :param remote_ip: The IP address from which the request originated. This
                      can be IPv4, IPv6, or a token which is derived from
                      the IP address, depending on the data that has been
                      provided in the error report.
    """

    def __init__(self, method=None, url=None,
                 user_agent=None, referrer=None,
                 response_status_code=None, remote_ip=None):
        self.method = method
        self.url = url
        # intentionally camel case for mapping to JSON API expects
        # pylint: disable=invalid-name
        self.userAgent = user_agent
        self.referrer = referrer
        self.responseStatusCode = response_status_code
        self.remoteIp = remote_ip


class Client(object):
    """Error Reporting client. Currently Error Reporting is done by creating
    a Logging client.

    :type project: str
    :param project: the project which the client acts on behalf of. If not
                    passed falls back to the default inferred from the
                    environment.

    :type credentials: :class:`oauth2client.client.OAuth2Credentials` or
                       :class:`NoneType`
    :param credentials: The OAuth2 Credentials to use for the connection
                        owned by this client. If not passed (and if no ``http``
                        object is passed), falls back to the default inferred
                        from the environment.

    :type http: :class:`httplib2.Http` or class that defines ``request()``.
    :param http: An optional HTTP object to make requests. If not passed, an
                 ``http`` object is created that is bound to the
                 ``credentials`` for the current object.

    :type service: str
    :param service: An identifier of the service, such as the name of the
                    executable, job, or Google App Engine service name. This
                    field is expected to have a low number of values that are
                    relatively stable over time, as opposed to version,
                    which can be changed whenever new code is deployed.


    :type version: str
    :param version: Represents the source code version that the developer
                    provided, which could represent a version label or a Git
                    SHA-1 hash, for example. If the developer did not provide
                    a version, the value is set to default.

    :type use_gax: bool
    :param use_gax: (Optional) Explicitly specifies whether
                    to use the gRPC transport (via GAX) or HTTP. If unset,
                    falls back to the ``GOOGLE_CLOUD_DISABLE_GRPC`` environment
                    variable.

    :raises: :class:`ValueError` if the project is neither passed in nor
             set in the environment.
    """

    def __init__(self, project=None,
                 credentials=None,
                 http=None,
                 service=None,
                 version=None,
                 use_gax=None):
        if project is None:
            self._project = _determine_default_project()
        else:
            self._project = project
        self._credentials = credentials
        self._http = http

        self._report_errors_api = None

        self.service = service if service else self.DEFAULT_SERVICE
        self.version = version
        if use_gax is None:
            self._use_gax = _USE_GAX
        else:
            self._use_gax = use_gax

    DEFAULT_SERVICE = 'python'

    @property
    def report_errors_api(self):
        """Helper for logging-related API calls.

        See:
        https://cloud.google.com/logging/docs/api/reference/rest/v2/entries
        https://cloud.google.com/logging/docs/api/reference/rest/v2/projects.logs

        :rtype:
            :class:`_gax._ErrorReportingGaxApi`
            or
            :class:`._logging._ErrorReportingLoggingAPI`
        :returns: A class that implements the report errors API.
        """
        if self._report_errors_api is None:
            if self._use_gax:
                self._report_errors_api = make_report_error_api(self)
            else:
                self._report_errors_api = _ErrorReportingLoggingAPI(
                    self._project, self._credentials, self._http)
        return self._report_errors_api

    def _build_error_report(self,
                            message,
                            report_location=None,
                            http_context=None,
                            user=None):
        """Builds the Error Reporting object to report.

        This builds the object according to

        https://cloud.google.com/error-reporting/docs/formatting-error-messages

        :type message: str
        :param message: The stack trace that was reported or logged by the
                   service.

        :type report_location: dict
        :param report_location:  The location in the source code where the
               decision was made to report the error, usually the place
               where it was logged. For a logged exception this would be the
               source line where the exception is logged, usually close to
               the place where it was caught.

               This should be a Python dict that contains the keys 'filePath',
               'lineNumber', and 'functionName'

        :type http_context: :class`google.cloud.error_reporting.HTTPContext`
        :param http_context: The HTTP request which was processed when the
                             error was triggered.

        :type user: str
        :param user: The user who caused or was affected by the crash. This can
                     be a user ID, an email address, or an arbitrary token that
                     uniquely identifies the user. When sending an error
                     report, leave this field empty if the user was not
                     logged in. In this  case the Error Reporting system will
                     use other data, such as remote IP address,
                     to distinguish affected users.
        :rtype: dict
        :returns: A dict payload ready to be serialized to JSON and sent to
                  the API.
         """
        payload = {
            'serviceContext': {
                'service': self.service,
            },
            'message': '{0}'.format(message)
        }

        if self.version:
            payload['serviceContext']['version'] = self.version

        if report_location or http_context or user:
            payload['context'] = {}

        if report_location:
            payload['context']['reportLocation'] = report_location

        if http_context:
            http_context_dict = http_context.__dict__
            # strip out None values
            payload['context']['httpContext'] = {
                key: value for key, value in six.iteritems(http_context_dict)
                if value is not None
            }

        if user:
            payload['context']['user'] = user
        return payload

    def _send_error_report(self,
                           message,
                           report_location=None,
                           http_context=None,
                           user=None):
        """Makes the call to the Error Reporting API.

        This is the lower-level interface to build and send the payload,
        generally users will use either report() or report_exception() to
        automatically gather the parameters for this method.

        :type message: str
        :param message: The stack trace that was reported or logged by the
                   service.

        :type report_location: dict
        :param report_location:  The location in the source code where the
               decision was made to report the error, usually the place
               where it was logged. For a logged exception this would be the
               source line where the exception is logged, usually close to
               the place where it was caught.

               This should be a Python dict that contains the keys 'filePath',
               'lineNumber', and 'functionName'

        :type http_context: :class`google.cloud.error_reporting.HTTPContext`
        :param http_context: The HTTP request which was processed when the
                             error was triggered.

        :type user: str
        :param user: The user who caused or was affected by the crash. This can
                     be a user ID, an email address, or an arbitrary token that
                     uniquely identifies the user. When sending an error
                     report, leave this field empty if the user was not
                     logged in. In this  case the Error Reporting system will
                     use other data, such as remote IP address,
                     to distinguish affected users.
        """
        error_report = self._build_error_report(message, report_location,
                                                http_context, user)
        self.report_errors_api.report_error_event(error_report)

    def report(self, message, http_context=None, user=None):
        """ Reports a message to Stackdriver Error Reporting

        https://cloud.google.com/error-reporting/docs/formatting-error-messages

        :type message: str
        :param message: A user-supplied message to report

        :type http_context: :class`google.cloud.error_reporting.HTTPContext`
        :param http_context: The HTTP request which was processed when the
                             error was triggered.

        :type user: str
        :param user: The user who caused or was affected by the crash. This
                     can be a user ID, an email address, or an arbitrary
                     token that uniquely identifies the user. When sending
                     an error report, leave this field empty if the user
                     was not logged in. In this case the Error Reporting
                     system will use other data, such as remote IP address,
                     to distinguish affected users.

        Example:

        .. code-block:: python

          >>>  client.report("Something went wrong!")
        """
        stack = traceback.extract_stack()
        last_call = stack[-2]
        file_path = last_call[0]
        line_number = last_call[1]
        function_name = last_call[2]
        report_location = {
            'filePath': file_path,
            'lineNumber': line_number,
            'functionName': function_name
        }

        self._send_error_report(message,
                                http_context=http_context,
                                user=user,
                                report_location=report_location)

    def report_exception(self, http_context=None, user=None):
        """ Reports the details of the latest exceptions to Stackdriver Error
            Reporting.

          :type http_context: :class`google.cloud.error_reporting.HTTPContext`
          :param http_context: The HTTP request which was processed when the
                               error was triggered.

          :type user: str
          :param user: The user who caused or was affected by the crash. This
                       can be a user ID, an email address, or an arbitrary
                       token that uniquely identifies the user. When sending an
                       error report, leave this field empty if the user was
                       not logged in. In this case the Error Reporting system
                       will use other data, such as remote IP address,
                       to distinguish affected users.

           Example::

                >>>     try:
                >>>         raise NameError
                >>>     except Exception:
                >>>         client.report_exception()
        """
        self._send_error_report(traceback.format_exc(),
                                http_context=http_context,
                                user=user)