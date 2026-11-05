"""Helpers for the design / price (stage 2) tests."""

from django.core.files.uploadedfile import SimpleUploadedFile

PDF = b"%PDF-1.4\n%test\n"


def design_file(design, name="a.pdf"):
    """Put one file into the design's first variant folder («Tayyor» needs a file)."""
    from filer.models import File

    from metering.design.models import Design

    if not isinstance(design, Design):
        design = Design.objects.get(pk=design)
    folder = design.designtype_set.first().folder
    f = File(folder=folder, original_filename=name)
    f.file.save(name, SimpleUploadedFile(name, PDF))
    return f
