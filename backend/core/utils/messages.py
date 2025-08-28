from django.contrib.messages import add_message

def instance_archive(request):
    return add_message(
        request, level=30,               
        message=f'Ушбу мижозга хизмат кўрсатилган',
    ) 