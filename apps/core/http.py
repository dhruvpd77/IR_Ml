from django.core.paginator import Paginator


def paginate(request, queryset, size=20):
    return Paginator(queryset, size).get_page(request.GET.get("page") or 1)


def querystring(request):
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()
