from django.db import models
from django.contrib.auth.models import User


class ControllerConfig(models.Model):
    """Singleton de configuração — um registro por usuário."""
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name='controller_config')
    anthropic_api_key = models.CharField(max_length=200, blank=True)
    github_token = models.CharField(max_length=200, blank=True)
    github_default_repo = models.CharField(max_length=200, blank=True)
    max_tokens_per_project = models.IntegerField(default=100_000)
    max_cost_usd_per_project = models.DecimalField(max_digits=8, decimal_places=2, default=5.00)
    controller_check_every_n_tokens = models.IntegerField(default=5_000)
    max_rounds_per_flow = models.IntegerField(default=20)
    auto_create_github_issues = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Config de {self.owner.username}'

    @classmethod
    def get_for_user(cls, user):
        config, _ = cls.objects.get_or_create(owner=user)
        return config

    def masked_anthropic_key(self):
        if self.anthropic_api_key:
            return '•' * 12 + self.anthropic_api_key[-4:]
        return ''

    def masked_github_token(self):
        if self.github_token:
            return '•' * 12 + self.github_token[-4:]
        return ''
