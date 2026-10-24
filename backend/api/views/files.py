"""Filer folders as an API: every Замер/Заказ/Дизайн/… row owns a folder (see
core/utils/filer.py), and the admin links to it with "Перейти". Here the SPA can
browse it, upload into it and keep the discussion attached to it."""

import os
import re

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.shortcuts import get_object_or_404
from filer.models import File, Folder, Image
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from discussion.models import DiscussionMessage

from ..folder_access import folder_rights
from ..serializers.common import UserShortSerializer

# Files are served from /media/ on the same origin as the SPA, whose tokens sit in
# localStorage — an uploaded .html/.svg/.js would run as the app. Only allow formats
# that browsers never execute.
ALLOWED_UPLOAD_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
    ".bmp",
    ".tif",
    ".tiff",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".txt",
    ".csv",
    ".zip",
    ".rar",
    ".7z",
    ".dwg",
    ".dxf",
    ".skp",
    ".3ds",
    ".max",
    ".obj",
    ".stl",
    ".mp4",
    ".mov",
    ".avi",
    ".mp3",
    ".m4a",
    ".ogg",
    ".psd",
    ".cdr",
    ".ai",
}
# Names the automatic folder layout uses (core/utils/filer.py, order/models.py …).
RESERVED_FOLDER_NAME = re.compile(r"^\s*(Заказ|Замер|Замеры)(-\d+)?\s*$", re.IGNORECASE)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _thumbnail(file):
    if not isinstance(file, Image):
        return None
    try:
        from easy_thumbnails.files import get_thumbnailer

        return get_thumbnailer(file.file)({"size": (320, 320), "crop": True}).url
    except Exception:  # a broken/missing image must not take the whole folder down
        return None


def _denied():
    from rest_framework.exceptions import PermissionDenied

    return PermissionDenied("Бу папкага рухсат йўқ.")


def _file_row(file, user=None, rights=None):
    can_delete = bool(
        rights and (rights["delete_any"] or (rights["upload"] and file.owner_id == user.pk))
    )
    return {
        "can_delete": can_delete,
        "id": file.pk,
        "name": file.original_filename or file.label,
        "url": file.url,
        "size": file.size,
        "mime_type": getattr(file, "mime_type", None),
        "is_image": isinstance(file, Image),
        "thumbnail": _thumbnail(file),
        "uploaded_at": file.uploaded_at,
        "owner": UserShortSerializer(file.owner).data if file.owner_id else None,
    }


def _breadcrumbs(folder):
    chain = []
    node = folder
    while node is not None and len(chain) < 20:
        chain.append({"id": node.pk, "name": node.name})
        node = node.parent
    return list(reversed(chain))


class MessageSerializer(serializers.ModelSerializer):
    author = UserShortSerializer(read_only=True)

    class Meta:
        model = DiscussionMessage
        fields = ["id", "author", "message", "created_at"]
        read_only_fields = ["author", "created_at"]


class FolderView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, folder_id):
        folder = get_object_or_404(Folder, pk=folder_id)
        rights = folder_rights(request.user, folder)
        if not rights["view"]:
            raise _denied()
        children = folder.children.annotate(n_files=Count("all_files")).order_by("name")
        files = File.objects.filter(folder=folder).select_related("owner").order_by("-uploaded_at")
        return Response(
            {
                "id": folder.pk,
                "name": folder.name,
                "parent": folder.parent_id,
                "breadcrumbs": _breadcrumbs(folder),
                "folders": [
                    {"id": child.pk, "name": child.name, "file_count": child.n_files}
                    for child in children
                ],
                "files": [_file_row(f, request.user, rights) for f in files],
                "rights": rights,
            }
        )

    def post(self, request, folder_id):
        """multipart `file` (one or many) → uploaded into this folder;
        JSON {"name": "..."} → a new sub-folder."""
        folder = get_object_or_404(Folder, pk=folder_id)
        rights = folder_rights(request.user, folder)
        uploads = request.FILES.getlist("file")
        if not uploads:
            if not rights["create_folder"]:
                raise _denied()
            name = (request.data.get("name") or "").strip()
            if not name:
                return Response({"detail": "Папка номини киритинг."}, status=400)
            if RESERVED_FOLDER_NAME.match(name):
                return Response({"detail": f"«{name}» — тизим папкаси номи."}, status=400)
            child, _ = Folder.objects.get_or_create(
                name=name, parent=folder, defaults={"owner": request.user}
            )
            return Response({"id": child.pk, "name": child.name}, status=status.HTTP_201_CREATED)

        if not rights["upload"]:
            raise _denied()
        for upload in uploads:
            ext = os.path.splitext(upload.name)[1].lower()
            if ext not in ALLOWED_UPLOAD_EXTENSIONS:
                return Response(
                    {"detail": f"«{upload.name}»: бундай файл турини юклаб бўлмайди."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        created = []
        for upload in uploads:
            ext = os.path.splitext(upload.name)[1].lower()
            model = Image if ext in IMAGE_EXTENSIONS else File
            obj = model(
                folder=folder,
                owner=request.user,
                original_filename=upload.name,
                file=upload,
            )
            obj.save()
            created.append(_file_row(obj, request.user, rights))
        return Response(created, status=status.HTTP_201_CREATED)


class FileView(APIView):
    def delete(self, request, file_id):
        file = get_object_or_404(File, pk=file_id)
        if file.folder_id:
            allowed = _file_row(file, request.user, folder_rights(request.user, file.folder))[
                "can_delete"
            ]
        else:  # unfiled file: no folder to work on, only the filer permission counts
            allowed = request.user.has_perm("filer.delete_file")
        if not allowed:
            raise _denied()
        file.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FolderMessagesView(APIView):
    """The DiscussionInline shown on the admin folder page."""

    def get(self, request, folder_id):
        folder = get_object_or_404(Folder, pk=folder_id)
        if not folder_rights(request.user, folder)["view"]:
            raise _denied()
        messages = DiscussionMessage.objects.filter(
            content_type=ContentType.objects.get_for_model(Folder), object_id=folder.pk
        ).select_related("author")
        return Response(MessageSerializer(messages, many=True).data)

    def post(self, request, folder_id):
        folder = get_object_or_404(Folder, pk=folder_id)
        if not folder_rights(request.user, folder)["comment"]:
            raise _denied()
        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            author=request.user,
            content_type=ContentType.objects.get_for_model(Folder),
            object_id=folder.pk,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
