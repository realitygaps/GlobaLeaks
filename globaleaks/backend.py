# -*- coding: UTF-8
#   backend
#   *******
# Here is the logic for creating a twisted service. In this part of the code we
# do all the necessary high level wiring to make everything work together.
# Specifically we create the cyclone web.Application from the API specification,
# we create a TCPServer for it and setup logging.
# We also set to kill the threadpool (the one used by Storm) when the
# application shuts down.

from twisted.application.service import Application
from twisted.application import internet
from cyclone import web
from globaleaks.settings import GLSetting
from globaleaks.rest import api

application = Application('GLBackend')

# Initialize the web API event listener, handling all the synchronous operations
GLBackendAPIFactory = web.Application(api.spec, debug=GLSetting.cyclone_debug)
GLBackendAPI = internet.TCPServer(GLSetting.bind_port, GLBackendAPIFactory)
GLBackendAPI.setServiceParent(application)

# define exit behaviour
