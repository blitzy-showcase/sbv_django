from django.apps.registry import Apps
from django.db import models


class CustomModelBase(models.base.ModelBase):
    pass


class ModelWithCustomBase(models.Model, metaclass=CustomModelBase):
    pass


class UnicodeModel(models.Model):
    title = models.CharField("ÚÑÍ¢ÓÐÉ", max_length=20, default="“Ðjáñgó”")

    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        verbose_name = "úñí©óðé µóðéø"
        verbose_name_plural = "úñí©óðé µóðéøß"

    def __str__(self):
        return self.title


class Unserializable:
    """
    An object that migration doesn't know how to serialize.
    """

    pass


class UnserializableModel(models.Model):
    title = models.CharField(max_length=20, default=Unserializable())

    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()


class UnmigratedModel(models.Model):
    """
    A model that is in a migration-less app (which this app is
    if its migrations directory has not been repointed)
    """

    pass


class EmptyManager(models.Manager):
    use_in_migrations = True


class FoodQuerySet(models.query.QuerySet):
    pass


class BaseFoodManager(models.Manager):
    def __init__(self, a, b, c=1, d=2):
        super().__init__()
        self.args = (a, b, c, d)


class FoodManager(BaseFoodManager.from_queryset(FoodQuerySet)):
    use_in_migrations = True


class NoMigrationFoodManager(BaseFoodManager.from_queryset(FoodQuerySet)):
    pass


# Test models with unique_together constraints for RenameIndex operation testing
# These models generate unnamed indexes that need proper handling during rename operations

class UniqueTogetherTestModel(models.Model):
    """
    Test model featuring multiple unique_together constraint combinations.
    Generates unnamed indexes to test various unnamed index generation patterns
    used in RenameIndex testing scenarios.
    """
    title = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    category = models.CharField(max_length=50)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        # Multiple unique_together combinations that generate unnamed indexes
        unique_together = [
            ('title', 'category'),
            ('slug', 'status'),
            ('category', 'status', 'created_at'),
        ]


class ComplexConstraintModel(models.Model):
    """
    Test model with mixed unique_together and explicit index definitions.
    Used to validate proper detection and handling of auto-generated versus
    explicitly named indexes during RenameIndex operations.
    """
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    email = models.EmailField()
    department = models.CharField(max_length=50)
    level = models.IntegerField()
    active = models.BooleanField(default=True)
    
    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        # Mix of unnamed (unique_together) and named constraints
        unique_together = [
            ('name', 'department'),
            ('code', 'level'),
        ]
        indexes = [
            # Explicitly named index for comparison with unnamed ones
            models.Index(fields=['email'], name='explicit_email_idx'),
            models.Index(fields=['department', 'active'], name='explicit_dept_active_idx'),
        ]


class MultiFieldUniqueModel(models.Model):
    """
    Test model with complex unique_together constraints spanning multiple field types.
    Tests comprehensive index name generation and restoration logic across
    different PostgreSQL column types and constraint patterns.
    """
    string_field = models.CharField(max_length=200)
    integer_field = models.IntegerField()
    decimal_field = models.DecimalField(max_digits=10, decimal_places=2)
    date_field = models.DateField()
    datetime_field = models.DateTimeField()
    boolean_field = models.BooleanField()
    text_field = models.TextField()
    foreign_key_field = models.ForeignKey(
        'UniqueTogetherTestModel', 
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        # Complex unique_together constraints with various field types
        unique_together = [
            ('string_field', 'integer_field'),
            ('decimal_field', 'date_field', 'boolean_field'),
            ('datetime_field', 'foreign_key_field'),
            ('string_field', 'text_field', 'integer_field'),
        ]


class PostgreSQLSpecificTestModel(models.Model):
    """
    Test model with PostgreSQL-specific field types and constraint patterns.
    Supports PostgreSQL-specific testing scenarios including different column types
    and constraint patterns that generate various auto-generated index naming patterns.
    """
    uuid_field = models.UUIDField(null=True, blank=True)
    json_field = models.JSONField(default=dict)
    array_field = models.CharField(max_length=100)  # Simulated array field
    inet_field = models.GenericIPAddressField(null=True, blank=True)
    big_integer_field = models.BigIntegerField()
    small_integer_field = models.SmallIntegerField()
    positive_integer_field = models.PositiveIntegerField()
    float_field = models.FloatField()
    duration_field = models.DurationField(null=True, blank=True)
    
    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        # PostgreSQL-specific constraint combinations
        unique_together = [
            ('uuid_field', 'big_integer_field'),
            ('inet_field', 'small_integer_field', 'positive_integer_field'),
            ('float_field', 'duration_field'),
            ('array_field', 'json_field'),
        ]


class SimpleUniqueModel(models.Model):
    """
    Simple test model with basic unique_together constraint.
    Provides baseline testing for Migration State Tracker component
    with predictable unique_together constraint configurations.
    """
    field_a = models.CharField(max_length=50)
    field_b = models.CharField(max_length=50)
    
    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        unique_together = [('field_a', 'field_b')]


class ThreeFieldUniqueModel(models.Model):
    """
    Test model with three-field unique_together constraint.
    Tests migration state tracking with multi-field unnamed index scenarios.
    """
    field_x = models.CharField(max_length=30)
    field_y = models.IntegerField()
    field_z = models.BooleanField()
    
    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        unique_together = [('field_x', 'field_y', 'field_z')]


class MixedConstraintTestModel(models.Model):
    """
    Test model combining various constraint types to validate proper
    unnamed index detection in complex scenarios with multiple constraint types.
    """
    primary_field = models.CharField(max_length=100)
    secondary_field = models.CharField(max_length=100)
    tertiary_field = models.CharField(max_length=100)
    numeric_field = models.IntegerField()
    flag_field = models.BooleanField(default=False)
    
    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        # Multiple unique_together constraints of different sizes
        unique_together = [
            ('primary_field', 'secondary_field'),
            ('tertiary_field', 'numeric_field', 'flag_field'),
            ('primary_field', 'tertiary_field'),
        ]


class EdgeCaseUniqueModel(models.Model):
    """
    Test model for edge cases in unique_together constraint handling.
    Tests scenarios with nullable fields, foreign keys, and special character handling
    in auto-generated index names.
    """
    # Fields with special characters that may affect index naming
    field_with_underscore = models.CharField(max_length=50)
    field_with_number_123 = models.CharField(max_length=50) 
    nullable_field = models.CharField(max_length=50, null=True, blank=True)
    foreign_key_nullable = models.ForeignKey(
        'SimpleUniqueModel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        # Edge case constraints with nullable and foreign key fields
        unique_together = [
            ('field_with_underscore', 'field_with_number_123'),
            ('nullable_field', 'foreign_key_nullable'),
        ]
