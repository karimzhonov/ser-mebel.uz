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

def get_tag(text, sev):
    color = sev_to_color(sev)
    return format_html(f"""
    <span class="inline-block font-semibold leading-normal px-2 py-1 rounded-default text-[11px] uppercase whitespace-nowrap {get_colors(color)}">
        {text}
    </span>
""")