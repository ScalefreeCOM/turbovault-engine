from django.db import models


class ChoiceCharField(models.CharField):
    """
    CharField that casts TextChoices members to plain str before binding.

    Snowflake's connector checks type(value) is str rather than
    isinstance(value, str), so TextChoices members (str subclasses) must be
    explicitly cast to str to avoid errors.
    """

    def get_db_prep_value(self, value, connection, prepared=False):
        value = super().get_db_prep_value(value, connection, prepared)
        if isinstance(value, str) and type(value) is not str:
            return str(value)
        return value

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        path = "django.db.models.CharField"
        return name, path, args, kwargs
