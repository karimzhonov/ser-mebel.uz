from django.shortcuts import redirect
from django.http import Http404

class Redirect404Middleware:
    def process_exception(self, request, exception):
        if isinstance(exception, Http404):
            return redirect("/admin/")