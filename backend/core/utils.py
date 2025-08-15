from django.utils.html import format_html
from django.conf import settings

def media(path):
    return f"{settings.MEDIA_URL}{path}"

def sev_to_color(sev):
    return {
        'success': 'green',
        'info': 'blue',
        'warning': 'orange',
        'danger': 'red',
        'secondary': 'white',
        'green': 'green',
        'orange': 'orange',
        'red': 'red',
        'blue': 'blue',
    }[sev]

def get_colors(sev):
    color = sev_to_color(sev)
    return f"bg-{color}-100 text-{color}-700 dark:bg-{color}-500/20 dark:text-{color}-400"

def get_tag(text, sev):
    color = sev_to_color(sev)
    return format_html(f"""
    <span class="inline-block font-semibold leading-normal px-2 py-1 rounded-default text-[11px] uppercase whitespace-nowrap {get_colors(color)}">
        {text}
    </span>
""")

def create_folder(instance, global_folder_name, folder_name = None):
    from filer.models.foldermodels import Folder
    
    created_history = instance.history.order_by('history_date').first()
    created_user = created_history.history_user if created_history else None

    global_folder, _ = Folder.objects.get_or_create(
        name=global_folder_name,
        defaults={'owner': created_user}
    )

    global_folder_pk, _ = Folder.objects.get_or_create(
        name=f'{global_folder_name}-{instance.pk}',
        defaults={
            "parent": global_folder,
            "owner": created_user
        }
    )
    if folder_name:
        folder, _ = Folder.objects.get_or_create(
            name=folder_name,
            defaults={
                "parent": global_folder_pk,
                "owner": created_user
            }
        )
    else:
        folder = global_folder_pk

    instance.folder = folder
    instance.save()

def get_folder_link(folder_id):
    return f"/admin/filer/folder/{folder_id}/list/"


def get_folder_link_html(folder_id):
    return format_html(f'<a class="text-blue-700" href="{get_folder_link(folder_id)}">Перейти</a>') if folder_id else '-'
