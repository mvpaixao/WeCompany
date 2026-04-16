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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    total_tokens_used = models.IntegerField(default=0)
    total_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    current_activity = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title

    @property
    def unread_count(self):
        return self.emails.filter(is_read=False).exclude(sender='user').count()

    @property
    def has_specs(self):
        return self.specs.exists()

    @property
    def spec_version(self):
        """Returns the current spec version number (1 = first, 2 = first delta, etc.)"""
        return self.specs.values('version').distinct().count()


class EmailMessage(models.Model):
    PERSONA_CHOICES = [
        ('user', 'Você'),
        ('po', 'Product Owner'),
        ('fc', 'Entrevistador de Campo'),
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
        ('fc', 'Entrevistador de Campo'),
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


class ProjectSpec(models.Model):
    """Specification document generated after consensus."""
    SPEC_TYPES = [
        ('ui',        'Spec de UI'),
        ('backend',   'Spec de Backend'),
        ('business',  'Business & Requisitos'),
        ('technical', 'Especificação Técnica'),
    ]
    VERSION_TYPES = [
        ('full',  'Especificação Completa'),
        ('delta', 'Delta — Alterações'),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='specs')
    spec_type = models.CharField(max_length=20, choices=SPEC_TYPES)
    version_type = models.CharField(max_length=10, choices=VERSION_TYPES, default='full')
    version = models.PositiveIntegerField(default=1)  # 1 = full, 2+ = delta rounds
    body = models.TextField()
    body_html = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['version', 'spec_type']

    def __str__(self):
        tag = 'Δ' if self.version_type == 'delta' else 'v1'
        return f'[{tag}] {self.get_spec_type_display()} — {self.project}'
