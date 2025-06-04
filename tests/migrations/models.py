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


# Test models for RenameIndex operations with unique_together constraints
# These models generate unnamed indexes that are used to test RenameIndex
# forward/backward migration cycles and unnamed index detection/restoration


class UniqueTogetherTestModel(models.Model):
    """
    Test model with multiple unique_together constraint combinations to test
    various unnamed index generation patterns used in RenameIndex testing scenarios.
    """
    title = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    category = models.CharField(max_length=50)
    status = models.IntegerField(default=1)
    created_date = models.DateField(auto_now_add=True)

    class Meta:
        # Disable auto loading of this model as we load it on our own
        apps = Apps()
        # Multiple unique_together constraints that generate unnamed indexes
        unique_together = [
            ('title', 'code'),          # Basic two-field unique constraint
            ('category', 'status'),     # Status code with category constraint
            ('title', 'category', 'status'),  # Three-field complex constraint
        ]


class ComplexConstraintModel(models.Model):
    """
    Test model with mixed unique_together and explicit index definitions to validate
    proper detection and handling of auto-generated versus explicitly named indexes.
    """
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    department_code = models.CharField(max_length=10)
    priority = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    version = models.CharField(max_length=20)

    class Meta:
        apps = Apps()
        # Mix of unique_together (generates unnamed indexes) and explicit indexes
        unique_together = [
            ('name', 'department_code'),    # Unnamed index from unique_together
            ('slug', 'version'),            # Another unnamed index
        ]
        indexes = [
            # Explicitly named index for comparison with unnamed ones
            models.Index(fields=['priority', 'is_active'], name='explicit_priority_active_idx'),
        ]


class MultiFieldUniqueModel(models.Model):
    """
    Test model with complex unique_together constraints spanning multiple field types
    to test comprehensive index name generation and restoration logic.
    """
    identifier = models.CharField(max_length=50)
    numeric_code = models.IntegerField()
    decimal_value = models.DecimalField(max_digits=10, decimal_places=2)
    text_field = models.TextField()
    url_field = models.URLField()
    email_field = models.EmailField()
    date_field = models.DateField()
    datetime_field = models.DateTimeField()
    boolean_field = models.BooleanField(default=False)

    class Meta:
        apps = Apps()
        # Complex unique_together constraints with various field types
        unique_together = [
            ('identifier', 'numeric_code'),                    # String + Integer
            ('decimal_value', 'boolean_field'),                # Decimal + Boolean  
            ('email_field', 'date_field'),                     # Email + Date
            ('url_field', 'datetime_field', 'boolean_field'),  # URL + DateTime + Boolean
            ('identifier', 'text_field', 'numeric_code'),      # Mixed types constraint
        ]


class PostgreSQLSpecificTestModel(models.Model):
    """
    Test model with PostgreSQL-specific field types and constraint patterns
    that generate various auto-generated index naming patterns.
    """
    uuid_field = models.UUIDField()
    json_field = models.JSONField(default=dict)
    array_field = models.CharField(max_length=100)  # Would be ArrayField in real PostgreSQL usage
    inet_address = models.GenericIPAddressField()
    big_integer = models.BigIntegerField()
    small_integer = models.SmallIntegerField()
    positive_big_integer = models.PositiveBigIntegerField()
    duration_field = models.DurationField()
    binary_field = models.BinaryField()

    class Meta:
        apps = Apps()
        # PostgreSQL-specific unique_together patterns
        unique_together = [
            ('uuid_field', 'inet_address'),                      # UUID + IP constraint
            ('big_integer', 'small_integer'),                    # Different integer types
            ('json_field', 'array_field'),                       # JSON + Array constraint
            ('positive_big_integer', 'duration_field'),          # Positive BigInt + Duration
            ('uuid_field', 'big_integer', 'inet_address'),      # Complex multi-type constraint
        ]


class MigrationStateTrackerModel(models.Model):
    """
    Test model with predictable unique_together constraint configurations
    to support Migration State Tracker component testing.
    """
    tracker_id = models.CharField(max_length=100)
    state_name = models.CharField(max_length=50)
    sequence_number = models.IntegerField()
    checkpoint_data = models.TextField()
    timestamp = models.DateTimeField()
    is_checkpoint = models.BooleanField(default=False)

    class Meta:
        apps = Apps()
        # Predictable unique_together configurations for state tracking tests
        unique_together = [
            ('tracker_id', 'sequence_number'),          # Sequence uniqueness per tracker
            ('state_name', 'checkpoint_data'),          # State name + data uniqueness
            ('tracker_id', 'timestamp', 'is_checkpoint'),  # Temporal uniqueness constraint
        ]


class ForeignKeyUniqueTogetherModel(models.Model):
    """
    Test model with ForeignKey fields in unique_together constraints
    to test index generation patterns with relational constraints.
    """
    related_unicode = models.ForeignKey(UnicodeModel, on_delete=models.CASCADE)
    related_unserializable = models.ForeignKey(UnserializableModel, on_delete=models.CASCADE)
    description = models.CharField(max_length=200)
    reference_code = models.CharField(max_length=50)
    priority_level = models.PositiveIntegerField()

    class Meta:
        apps = Apps()
        # unique_together with ForeignKey fields generates specific index patterns
        unique_together = [
            ('related_unicode', 'reference_code'),              # FK + CharField constraint
            ('related_unserializable', 'priority_level'),      # FK + Integer constraint
            ('related_unicode', 'related_unserializable'),     # Multiple FK constraint
            ('description', 'reference_code', 'priority_level'),  # Non-FK multi-field
        ]


class EdgeCaseUniqueModel(models.Model):
    """
    Test model for edge cases in unique_together constraint handling
    during RenameIndex operations.
    """
    # Fields that might cause edge cases in index naming
    field_with_underscores = models.CharField(max_length=100)
    field_with_numbers123 = models.IntegerField()
    very_long_field_name_that_might_cause_truncation_issues = models.CharField(max_length=50)
    field_with_special_chars = models.CharField(max_length=100)  # Would test special char handling
    
    class Meta:
        apps = Apps()
        # Edge case unique_together patterns for testing robustness
        unique_together = [
            ('field_with_underscores', 'field_with_numbers123'),  # Underscore + numeric
            ('very_long_field_name_that_might_cause_truncation_issues', 'field_with_special_chars'),  # Long names
            ('field_with_underscores', 'very_long_field_name_that_might_cause_truncation_issues', 'field_with_numbers123'),  # Complex edge case
        ]


class SimpleUniqueTogetherModel(models.Model):
    """
    Simplified test model for basic RenameIndex operation validation
    with minimal unique_together constraints.
    """
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)

    class Meta:
        apps = Apps()
        # Single simple unique_together constraint for basic testing
        unique_together = [
            ('name', 'code'),
        ]
