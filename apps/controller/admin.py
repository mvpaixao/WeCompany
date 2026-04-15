from django.contrib import admin
from .models import ControllerConfig


@admin.register(ControllerConfig)
class ControllerConfigAdmin(admin.ModelAdmin):
    list_display = ['owner', 'max_tokens_per_project', 'max_cost_usd_per_project', 'updated_at']
    exclude = ['anthropic_api_key', 'github_token']
