from django.urls import include, path
from utilities.urls import get_model_urls

from . import views  # noqa: F401  (registers the model views)

app_name = "netbox_naming"

urlpatterns = [
    path("generate/", views.GenerateNamesView.as_view(), name="generate"),
    path("namingconvention/", include(get_model_urls("netbox_naming", "namingconvention", detail=False))),
    path(
        "namingconvention/<int:pk>/",
        include(get_model_urls("netbox_naming", "namingconvention")),
    ),
    path("preview/", views.TemplatePreviewView.as_view(), name="namingconvention_preview"),
]
