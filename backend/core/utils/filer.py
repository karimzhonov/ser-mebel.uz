from django.db.transaction import atomic


@atomic
def copy_folder(folder, target_parent, name=None):
    """
    Копирует папку вместе с содержимым в другой parent folder.
    :param folder: исходная папка
    :param target_parent: куда вставить (или None для root)
    :return: новая папка
    """
    from filer.models import Folder, File

    # создаём новую папку
    new_folder = Folder.objects.create(
        name=name or folder.name,
        parent=target_parent,
        owner=folder.owner
    )

    # копируем все файлы
    for f in File.objects.filter(folder=folder):
        File.objects.create(
            folder=new_folder,
            owner=f.owner,
            original_filename=f.original_filename,
            file=f.file,   # ⚠️ это ссылается на тот же файл в storage, а не дублирует его
        )

    # рекурсивно копируем подпапки
    for child in Folder.objects.filter(parent=folder):
        copy_folder(child, new_folder)

    return new_folder


@atomic
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
    return folder