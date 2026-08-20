import pytest
from django.core.management import call_command
from django.test import Client


@pytest.mark.django_db
def test_wsgi_serves_collected_admin_static_assets(tmp_path, settings):
    settings.DEBUG = False
    settings.WHITENOISE_AUTOREFRESH = False
    settings.STATIC_ROOT = tmp_path
    settings.STATIC_URL = "/static/"

    call_command("collectstatic", interactive=False, verbosity=0)

    response = Client().get("/static/admin/css/base.css")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/css")
