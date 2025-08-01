from django.utils.html import format_html

def sev_to_color(sev):
    return {
        'success': 'green',
        'info': 'blue',
        'warning': 'orange',
        'danger': 'red',
        'secondary': 'white',
    }[sev]

def get_tag(text, sev):
    color = sev_to_color(sev)
    return format_html(f"""
    <span class="inline-block font-semibold leading-normal px-2 py-1 rounded-default text-[11px] uppercase whitespace-nowrap bg-{color}-100 text-{color}-700 dark:bg-{color}-500/20 dark:text-{color}-400">
        {text}
    </span>
""")