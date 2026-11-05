from core.bootstrap import ensure_reference_data


class ReferenceDataMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/static/") or path.startswith("/health"):
            return self.get_response(request)
        ensure_reference_data()
        return self.get_response(request)
