from unfold.admin import ModelAdmin as _ModelAdmin


class ModelAdmin(_ModelAdmin):

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save_and_continue"] = False
        extra_context["show_save_and_add_another"] = False
        # if object_id:
        #     extra_context["show_save"] = False
        return super().changeform_view(request, object_id, form_url, extra_context)

    def has_add_permission(self, request) -> bool:
        if request.resolver_match.view_name.endswith("changelist") or request.resolver_match.view_name.endswith("change"):
            return False
        return super().has_add_permission(request)
