from django.utils.html import format_html


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

def get_tag_html(text, sev):
    return f"""
    <span class="inline-block font-semibold leading-normal px-2 py-1 rounded-default text-[12px] uppercase whitespace-nowrap {get_colors(sev)}">
        {text}
    </span>
"""

def get_tag(text, sev):
    return format_html(get_tag_html(text, sev))


def get_folder_link(folder_id):
    return f"/admin/filer/folder/{folder_id}/list/"


def get_folder_link_html(folder_id):
    return format_html(f'<a class="text-blue-700" href="{get_folder_link(folder_id)}">Перейти</a>') if folder_id else '-'


def get_boolean_icons(booleans):
    tags = [
        get_tag_html(f'''<span class="material-symbols-outlined">{'check' if boolean else 'close'}</span>''', 'success' if boolean else 'danger')
        for boolean in booleans
    ]
    return format_html(f"""
<div class="flex flex-row gap-3">{" ".join(tags)}</div>
""")
