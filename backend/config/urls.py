"""URL configuration: the Django admin and the planning API."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('planner.urls')),
]
