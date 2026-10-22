from django import forms

from .templating import CF_PREFIX, TOKENS

__all__ = ("TemplateInput",)


class TemplateInput(forms.TextInput):
    """Template input with a live preview region and the list of available tokens."""

    template_name = "netbox_naming/widgets/template_input.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["pk"] = self.attrs.get("data-pk")
        context["widget"]["tokens"] = [*sorted(TOKENS), f"{CF_PREFIX}<name>"]
        return context
