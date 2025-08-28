

def not_add_permission_in_admin(request):
    if request.resolver_match.view_name.endswith("changelist") or request.resolver_match.view_name.endswith("change"):
        return False
    return True
