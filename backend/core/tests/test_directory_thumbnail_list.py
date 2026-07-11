import pytest
from django.urls import reverse

from filer.models import File, Folder, Image


@pytest.mark.django_db
def test_directory_thumbnail_list_renders_with_lightbox_markup(logged_in_admin_client, png_upload):
    folder = Folder.objects.create(name="test-thumb-folder")
    image = Image.objects.create(
        folder=folder, file=png_upload("pic.png"), original_filename="pic.png"
    )
    text_file = File.objects.create(
        folder=folder,
        file=png_upload("doc.txt"),  # content doesn't matter, only file_type does
        original_filename="doc.txt",
    )
    assert image.file_type == "Image"
    assert text_file.file_type == "File"

    url = reverse("admin:filer-directory_listing", kwargs={"folder_id": folder.id})
    response = logged_in_admin_client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    # Image items open the Alpine.js lightbox instead of navigating away.
    assert "openLightbox(" in content
    assert "lightboxOpen" in content
    # The url is rendered through |escapejs (hyphens become -), so compare
    # against the de-escaped content rather than the raw url.
    assert image.url in content.replace("\\u002D", "-")

    # Non-image files still get a normal link to their change form.
    assert text_file.get_admin_change_url() in content
