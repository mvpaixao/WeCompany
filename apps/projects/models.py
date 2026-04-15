from django.db import models
from django.contrib.auth.models import User


class Project(models.Model):
    STATUS = [
        ('active', 'Ativo'),
        ('dormant', 'Aguardando feedback'),
        ('completed', 'Concluído'),
        ('paused', 'Pausado pelo Controller'),
    ]
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
    title = models.CharField(max_length=255)
    original_idea = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS, default='active')
    github_repo = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    total_tokens_used = models.IntegerField(default=0)
    total_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title

    @property
    def unread_count(self):
        return self.emails.filter(is_read=False).exclude(sender='user').count()


class EmailMessage(models.Model):
    PERSONA_CHOICES = [
        ('user', 'Você'),
        ('po', 'Product Owner'),
        ('pm', 'Project Manager'),
        ('el', 'Engineering Lead'),
        ('dev1', 'Developer (Frontend)'),
        ('dev2', 'Developer (Backend)'),
        ('system', 'Sistema'),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='emails')
    sender = models.CharField(max_length=20, choices=PERSONA_CHOICES)
    recipients = models.JSONField(default=list)
    cc = models.JSONField(default=list)
    subject = models.CharField(max_length=500)
    body = models.TextField()
    body_html = models.TextField(blank=True)
    attachments = models.JSONField(default=list)
    in_reply_to = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='replies'
    )
    tokens_used = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'[{self.get_sender_display()}] {self.subject}'

    @property
    def recipients_display(self):
        labels = dict(self.PERSONA_CHOICES)
        return ', '.join(labels.get(r, r) for r in self.recipients)

    @property
    def cc_display(self):
        labels = dict(self.PERSONA_CHOICES)
        return ', '.join(labels.get(r, r) for r in self.cc)


class PersonaState(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pendente'),
        ('approved', 'Aprovado'),
        ('blocked', 'Bloqueado'),
    ]
    PERSONA_CHOICES = [
        ('po', 'Product Owner'),
        ('pm', 'Project Manager'),
        ('el', 'Engineering Lead'),
        ('dev1', 'Developer (Frontend)'),
        ('dev2', 'Developer (Backend)'),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='states')
    persona = models.CharField(max_length=20, choices=PERSONA_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    last_concern = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('project', 'persona')

    def __str__(self):
        return f'{self.project} — {self.get_persona_display()}: {self.status}'


class GitHubIssue(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='issues')
    github_issue_number = models.IntegerField(null=True, blank=True)
    github_url = models.URLField(blank=True)
    title = models.CharField(max_length=500)
    body = models.TextField()
    labels = models.JSONField(default=list)
    assignee = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'#{self.github_issue_number} {self.title}'
