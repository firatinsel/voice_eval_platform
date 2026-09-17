from django.contrib import admin
from django.urls import path
from reports.views import quality_report_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("report/", quality_report_view, name="quality-report"),
]