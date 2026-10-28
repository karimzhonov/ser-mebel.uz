"""Filer folders as an API: every Замер/Заказ/Дизайн/… row owns a folder (see
core/utils/filer.py), and the admin links to it with "Перейти". Here the SPA can
browse it, upload into it and keep the discussion attached to it."""

import os
import re
import zipfile

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from filer.models import File, Folder, Image
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from discussion.models import DiscussionMessage

from ..permissions import require_perm
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
# Phones (Telegram WebApp, iOS Files) often send names like "pdf (3)" with no
# extension; such a file was refused here, and saved elsewhere it is served as
# application/octet-stream, so it doesn't open. The real type is read from the
# content (magic bytes) or the browser's content type and the extension added.
_MAGIC = [
    (b"%PDF", ".pdf"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG", ".png"),
    (b"GIF8", ".gif"),
]
_CONTENT_TYPE_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/vnd.rar": ".rar",
    "application/x-rar-compressed": ".rar",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}
# Names that say nothing about the file ("pdf (3)", "document", "image_12").
_GENERIC_NAME = re.compile(
    r"^(pdf|file|fayl|document|doc|docx|xls|xlsx|csv|image|img|photo|scan|download|untitled)?"
    r"[\s_\-()\d]*$",
    re.IGNORECASE,
)


# Never accepted, whatever the content type claims (the browser could run them).
_REFUSED_EXTENSIONS = {
    ".html",
    ".htm",
    ".xhtml",
    ".svg",
    ".svgz",
    ".js",
    ".mjs",
    ".exe",
    ".msi",
    ".bat",
    ".cmd",
    ".sh",
    ".php",
    ".py",
    ".jar",
    ".apk",
    ".com",
    ".scr",
    ".vbs",
    ".ps1",
}
# Types with a reliable signature: trusted only when the bytes match it.
_SIGNED_EXTENSIONS = {".pdf", ".jpg", ".png", ".gif", ".webp"}
# ".pdf", ".docx" — but not ".05" from "scan 2024.05"
_REAL_EXTENSION = re.compile(r"^\.(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,5}$")
_CONTROL_AND_PATH = re.compile(r'[\x00-\x1f\x7f\\/:*?"<>|]+')


def _sniff(head: bytes):
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def _detect_extension(upload):
    head = upload.read(16)
    upload.seek(0)
    sniffed = _sniff(head)
    if sniffed:
        return sniffed
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    claimed = _CONTENT_TYPE_EXT.get(content_type)
    if claimed in _SIGNED_EXTENSIONS:
        return None  # says PDF / image but the bytes aren't — refuse, don't trust the header
    return claimed


def _client_name_for(folder):
    """Client of the order / metering that owns this folder (or a parent of it)."""
    from metering.models import Metering
    from order.models import Order

    ids, node = [], folder
    while node is not None and len(ids) < 20:
        ids.append(node.pk)
        node = node.parent
    for model in (Order, Metering):
        owner = model.objects.filter(folder_id__in=ids).select_related("client").first()
        if owner is not None and owner.client_id:
            return owner.client.fio
    return None


def _normalize_upload_name(upload, client_name):
    """Return the name to store the upload under (always with a known extension),
    or None when the file must be refused.

    Only a name WITHOUT a real extension ("pdf (3)") is completed from the content;
    a name with any other extension (".exe", ".html" …) is refused as before.
    `client_name` is a callable, evaluated at most once per request.
    """
    name = _CONTROL_AND_PATH.sub(" ", upload.name).strip()
    stem, ext = os.path.splitext(name)
    if ext.lower() in ALLOWED_UPLOAD_EXTENSIONS:
        return name
    if ext.lower() in _REFUSED_EXTENSIONS:
        return None
    if _REAL_EXTENSION.match(ext):
        # "Karimov.Smeta" looks like it has an extension; accept it only when the
        # bytes are a signed type (PDF / image), never on the content type alone.
        head = upload.read(16)
        upload.seek(0)
        if not _sniff(head):
            return None
    detected = _detect_extension(upload)
    if detected is None:
        return None
    base = name  # e.g. "pdf (3)": no real extension, the whole name is the stem
    if not base or _GENERIC_NAME.match(base):
        base = client_name() or base or "fayl"
    base = _CONTROL_AND_PATH.sub(" ", base).strip()[:120] or "fayl"
    return f"{base}{detected}"


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _thumbnail(file):
    if not isinstance(file, Image):
        return None
    try:
        from easy_thumbnails.files import get_thumbnailer

        return get_thumbnailer(file.file)({"size": (320, 320), "crop": True}).url
    except Exception:  # a broken/missing image must not take the whole folder down
        return None


# A name that is only a type word ("xlsx", "pdf (2)"): the word is the extension.
_NAME_IS_EXT = re.compile(r"^(pdf|docx?|xlsx?|pptx?|csv|zip|rar)[\s_\-()\d]*$", re.IGNORECASE)


def _zip_office_ext(fh) -> str | None:
    """.xlsx/.docx/.pptx are zip files: tell them apart by what is inside."""
    try:
        names = zipfile.ZipFile(fh).namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    for prefix, ext in (("xl/", ".xlsx"), ("word/", ".docx"), ("ppt/", ".pptx")):
        if any(n.startswith(prefix) for n in names):
            return ext
    return ".zip"


def _download_name(file, name):
    """Files saved before the upload fix may have no extension ("pdf (3)", "xlsx");
    phones then save them as an unknown type and they don't open. Read their bytes
    (PDF/images by signature, Office files by their zip contents) or take the type word
    of the name, and offer a download name with the right extension. Nothing is
    changed on disk."""
    if not name or _REAL_EXTENSION.match(os.path.splitext(name)[1]):
        return None
    ext = None
    try:
        with file.file.open("rb") as fh:
            head = fh.read(16)
            ext = _sniff(head)
            if not ext and head.startswith(b"PK\x03\x04"):
                fh.seek(0)
                ext = _zip_office_ext(fh)
    except Exception:  # missing file on disk etc. — fall back to the name
        ext = None
    if not ext:
        m = _NAME_IS_EXT.match(name.strip())
        ext = f".{m.group(1).lower()}" if m else None
    return f"{name}{ext}" if ext else None


def _file_row(file):
    name = file.original_filename or file.label
    return {
        "id": file.pk,
        "download_name": _download_name(file, name),
        "name": name,
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
        require_perm(request.user, "filer.view_folder")
        folder = get_object_or_404(Folder, pk=folder_id)
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
                "files": [_file_row(f) for f in files],
            }
        )

    def post(self, request, folder_id):
        """multipart `file` (one or many) → uploaded into this folder;
        JSON {"name": "..."} → a new sub-folder."""
        folder = get_object_or_404(Folder, pk=folder_id)
        uploads = request.FILES.getlist("file")
        if not uploads:
            require_perm(request.user, "filer.add_folder")
            name = (request.data.get("name") or "").strip()
            if not name:
                return Response({"detail": "Papka nomini kiriting."}, status=400)
            child, _ = Folder.objects.get_or_create(
                name=name, parent=folder, defaults={"owner": request.user}
            )
            return Response({"id": child.pk, "name": child.name}, status=status.HTTP_201_CREATED)

        require_perm(request.user, "filer.add_file")
        cache = {}

        def client_name():
            if "name" not in cache:
                cache["name"] = _client_name_for(folder)
            return cache["name"]

        for upload in uploads:
            name = _normalize_upload_name(upload, client_name)
            if name is None:
                return Response(
                    {
                        "detail": f"«{upload.name}»: fayl turini aniqlab bo'lmadi yoki bunday "
                        "turdagi faylni yuklab bo'lmaydi (PDF, rasm, Word, Excel …)."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            upload.name = name  # also the stored path, so /media/… ends with the extension
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
            created.append(_file_row(obj))
        return Response(created, status=status.HTTP_201_CREATED)


class FileView(APIView):
    def get(self, request, file_id):
        """The file itself as a download, under a name with the right extension. The
        SPA uses this instead of the bare /media/ link: a missing file is a clear 404
        here, not the server's redirect to /admin/ saved as the "file"."""
        require_perm(request.user, "filer.view_folder")
        f = get_object_or_404(File, pk=file_id)
        name = f.original_filename or f.label or "fayl"
        filename = _download_name(f, name) or name
        try:
            fh = f.file.open("rb")
        except (FileNotFoundError, OSError, ValueError):
            # 410, not 404: the server's nginx turns every 404 into a redirect to /admin/
            return Response(
                {"detail": "Fayl serverda topilmadi (diskda yo'q)."}, status=status.HTTP_410_GONE
            )
        return FileResponse(fh, as_attachment=True, filename=filename)

    def delete(self, request, file_id):
        require_perm(request.user, "filer.delete_file")
        get_object_or_404(File, pk=file_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FolderMessagesView(APIView):
    """The DiscussionInline shown on the admin folder page."""

    def get(self, request, folder_id):
        require_perm(request.user, "filer.view_folder")
        folder = get_object_or_404(Folder, pk=folder_id)
        messages = DiscussionMessage.objects.filter(
            content_type=ContentType.objects.get_for_model(Folder), object_id=folder.pk
        ).select_related("author")
        return Response(MessageSerializer(messages, many=True).data)

    def post(self, request, folder_id):
        require_perm(request.user, "filer.view_folder", "discussion.add_discussionmessage")
        folder = get_object_or_404(Folder, pk=folder_id)
        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            author=request.user,
            content_type=ContentType.objects.get_for_model(Folder),
            object_id=folder.pk,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
