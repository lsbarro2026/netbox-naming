from netbox.api.routers import NetBoxRouter

from . import views

app_name = "netbox_naming"

router = NetBoxRouter()
router.register("namingconventions", views.NamingConventionViewSet)

urlpatterns = router.urls
