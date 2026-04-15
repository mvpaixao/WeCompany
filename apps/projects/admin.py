from django.contrib import admin
from .models import Project, EmailMessage, PersonaState, GitHubIssue


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['title', 'owner', 'status', 'total_tokens_used', 'total_cost_usd', 'updated_at']
    list_filter = ['status']
    search_fields = ['title', 'owner__username']


@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    list_display = ['sender', 'subject', 'project', 'tokens_used', 'created_at']
    list_filter = ['sender']
    search_fields = ['subject', 'body']


@admin.register(PersonaState)
class PersonaStateAdmin(admin.ModelAdmin):
    list_display = ['project', 'persona', 'status', 'updated_at']
    list_filter = ['persona', 'status']


@admin.register(GitHubIssue)
class GitHubIssueAdmin(admin.ModelAdmin):
    list_display = ['title', 'project', 'github_issue_number', 'github_url', 'created_at']
