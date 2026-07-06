import uuid

from django.db import models

# Create your models here.
class User(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now=False)
    FullName = models.CharField(max_length=100)
    EmailAddress = models.EmailField()
    Password = models.CharField(max_length=100)
    Role = models.CharField(max_length=100)
    Status = models.CharField(max_length=100)
    UpdatedAt = models.DateTimeField(auto_now=False)