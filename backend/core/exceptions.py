class ServiceError(Exception):
    """A business rule refused the operation (e.g. "this metering is archived").

    Raised by `<app>/services.py` functions. The REST API turns it into a 400 with
    the message as `detail` (see api/exceptions.py), so keep the message readable
    by staff — it is shown to them verbatim.
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ServiceConflict(ServiceError):
    """ "Already done" (someone answered the request, the holiday was decided ...).
    The site API shows it as a 400 like any ServiceError; the bot API as a 409."""


class ServiceForbidden(ServiceError):
    """The acting person's role does not allow this. 400 on the site, 403 in the bot API."""
