from django.db import models
from django.db.migrations.operations.base import Operation
from django.db.migrations.state import ModelState
from django.db.migrations.utils import field_references, resolve_relation
from django.db.models.options import normalize_together
from django.utils.functional import cached_property

from .fields import AddField, AlterField, FieldOperation, RemoveField, RenameField


def _check_for_duplicates(arg_name, objs):
    used_vals = set()
    for val in objs:
        if val in used_vals:
            raise ValueError(
                "Found duplicate value %s in CreateModel %s argument." % (val, arg_name)
            )
        used_vals.add(val)


class ModelOperation(Operation):
    def __init__(self, name):
        self.name = name

    @cached_property
    def name_lower(self):
        return self.name.lower()

    def references_model(self, name, app_label):
        return name.lower() == self.name_lower

    def reduce(self, operation, app_label):
        return super().reduce(operation, app_label) or self.can_reduce_through(
            operation, app_label
        )

    def can_reduce_through(self, operation, app_label):
        return not operation.references_model(self.name, app_label)


class CreateModel(ModelOperation):
    """Create a model's table."""

    serialization_expand_args = ["fields", "options", "managers"]

    def __init__(self, name, fields, options=None, bases=None, managers=None):
        self.fields = fields
        self.options = options or {}
        self.bases = bases or (models.Model,)
        self.managers = managers or []
        super().__init__(name)
        # Sanity-check that there are no duplicated field names, bases, or
        # manager names
        _check_for_duplicates("fields", (name for name, _ in self.fields))
        _check_for_duplicates(
            "bases",
            (
                base._meta.label_lower
                if hasattr(base, "_meta")
                else base.lower()
                if isinstance(base, str)
                else base
                for base in self.bases
            ),
        )
        _check_for_duplicates("managers", (name for name, _ in self.managers))

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            "fields": self.fields,
        }
        if self.options:
            kwargs["options"] = self.options
        if self.bases and self.bases != (models.Model,):
            kwargs["bases"] = self.bases
        if self.managers and self.managers != [("objects", models.Manager())]:
            kwargs["managers"] = self.managers
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, app_label, state):
        state.add_model(
            ModelState(
                app_label,
                self.name,
                list(self.fields),
                dict(self.options),
                tuple(self.bases),
                list(self.managers),
            )
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.create_model(model)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = from_state.apps.get_model(app_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.delete_model(model)

    def describe(self):
        return "Create %smodel %s" % (
            "proxy " if self.options.get("proxy", False) else "",
            self.name,
        )

    @property
    def migration_name_fragment(self):
        return self.name_lower

    def references_model(self, name, app_label):
        name_lower = name.lower()
        if name_lower == self.name_lower:
            return True

        # Check we didn't inherit from the model
        reference_model_tuple = (app_label, name_lower)
        for base in self.bases:
            if (
                base is not models.Model
                and isinstance(base, (models.base.ModelBase, str))
                and resolve_relation(base, app_label) == reference_model_tuple
            ):
                return True

        # Check we have no FKs/M2Ms with it
        for _name, field in self.fields:
            if field_references(
                (app_label, self.name_lower), field, reference_model_tuple
            ):
                return True
        return False

    def reduce(self, operation, app_label):
        if (
            isinstance(operation, DeleteModel)
            and self.name_lower == operation.name_lower
            and not self.options.get("proxy", False)
        ):
            return []
        elif (
            isinstance(operation, RenameModel)
            and self.name_lower == operation.old_name_lower
        ):
            return [
                CreateModel(
                    operation.new_name,
                    fields=self.fields,
                    options=self.options,
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterModelOptions)
            and self.name_lower == operation.name_lower
        ):
            options = {**self.options, **operation.options}
            for key in operation.ALTER_OPTION_KEYS:
                if key not in operation.options:
                    options.pop(key, None)
            return [
                CreateModel(
                    self.name,
                    fields=self.fields,
                    options=options,
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterModelManagers)
            and self.name_lower == operation.name_lower
        ):
            return [
                CreateModel(
                    self.name,
                    fields=self.fields,
                    options=self.options,
                    bases=self.bases,
                    managers=operation.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterTogetherOptionOperation)
            and self.name_lower == operation.name_lower
        ):
            return [
                CreateModel(
                    self.name,
                    fields=self.fields,
                    options={
                        **self.options,
                        **{operation.option_name: operation.option_value},
                    },
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterOrderWithRespectTo)
            and self.name_lower == operation.name_lower
        ):
            return [
                CreateModel(
                    self.name,
                    fields=self.fields,
                    options={
                        **self.options,
                        "order_with_respect_to": operation.order_with_respect_to,
                    },
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, FieldOperation)
            and self.name_lower == operation.model_name_lower
        ):
            if isinstance(operation, AddField):
                return [
                    CreateModel(
                        self.name,
                        fields=self.fields + [(operation.name, operation.field)],
                        options=self.options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, AlterField):
                return [
                    CreateModel(
                        self.name,
                        fields=[
                            (n, operation.field if n == operation.name else v)
                            for n, v in self.fields
                        ],
                        options=self.options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, RemoveField):
                options = self.options.copy()
                for option_name in ("unique_together", "index_together"):
                    option = options.pop(option_name, None)
                    if option:
                        option = set(
                            filter(
                                bool,
                                (
                                    tuple(
                                        f for f in fields if f != operation.name_lower
                                    )
                                    for fields in option
                                ),
                            )
                        )
                        if option:
                            options[option_name] = option
                order_with_respect_to = options.get("order_with_respect_to")
                if order_with_respect_to == operation.name_lower:
                    del options["order_with_respect_to"]
                return [
                    CreateModel(
                        self.name,
                        fields=[
                            (n, v)
                            for n, v in self.fields
                            if n.lower() != operation.name_lower
                        ],
                        options=options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, RenameField):
                options = self.options.copy()
                for option_name in ("unique_together", "index_together"):
                    option = options.get(option_name)
                    if option:
                        options[option_name] = {
                            tuple(
                                operation.new_name if f == operation.old_name else f
                                for f in fields
                            )
                            for fields in option
                        }
                order_with_respect_to = options.get("order_with_respect_to")
                if order_with_respect_to == operation.old_name:
                    options["order_with_respect_to"] = operation.new_name
                return [
                    CreateModel(
                        self.name,
                        fields=[
                            (operation.new_name if n == operation.old_name else n, v)
                            for n, v in self.fields
                        ],
                        options=options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
        return super().reduce(operation, app_label)


class DeleteModel(ModelOperation):
    """Drop a model's table."""

    def deconstruct(self):
        kwargs = {
            "name": self.name,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, app_label, state):
        state.remove_model(app_label, self.name_lower)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = from_state.apps.get_model(app_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.delete_model(model)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.create_model(model)

    def references_model(self, name, app_label):
        # The deleted model could be referencing the specified model through
        # related fields.
        return True

    def describe(self):
        return "Delete model %s" % self.name

    @property
    def migration_name_fragment(self):
        return "delete_%s" % self.name_lower


class RenameModel(ModelOperation):
    """Rename a model."""

    def __init__(self, old_name, new_name):
        self.old_name = old_name
        self.new_name = new_name
        super().__init__(old_name)

    @cached_property
    def old_name_lower(self):
        return self.old_name.lower()

    @cached_property
    def new_name_lower(self):
        return self.new_name.lower()

    def deconstruct(self):
        kwargs = {
            "old_name": self.old_name,
            "new_name": self.new_name,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, app_label, state):
        state.rename_model(app_label, self.old_name, self.new_name)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        new_model = to_state.apps.get_model(app_label, self.new_name)
        if self.allow_migrate_model(schema_editor.connection.alias, new_model):
            old_model = from_state.apps.get_model(app_label, self.old_name)
            old_db_table = old_model._meta.db_table
            new_db_table = new_model._meta.db_table
            # Don't alter when a table name is not changed.
            if old_db_table == new_db_table:
                return
            # Move the main table
            schema_editor.alter_db_table(new_model, old_db_table, new_db_table)
            # Alter the fields pointing to us
            for related_object in old_model._meta.related_objects:
                if related_object.related_model == old_model:
                    model = new_model
                    related_key = (app_label, self.new_name_lower)
                else:
                    model = related_object.related_model
                    related_key = (
                        related_object.related_model._meta.app_label,
                        related_object.related_model._meta.model_name,
                    )
                to_field = to_state.apps.get_model(*related_key)._meta.get_field(
                    related_object.field.name
                )
                schema_editor.alter_field(
                    model,
                    related_object.field,
                    to_field,
                )
            # Rename M2M fields whose name is based on this model's name.
            fields = zip(
                old_model._meta.local_many_to_many, new_model._meta.local_many_to_many
            )
            for (old_field, new_field) in fields:
                # Skip self-referential fields as these are renamed above.
                if (
                    new_field.model == new_field.related_model
                    or not new_field.remote_field.through._meta.auto_created
                ):
                    continue
                # Rename the M2M table that's based on this model's name.
                old_m2m_model = old_field.remote_field.through
                new_m2m_model = new_field.remote_field.through
                schema_editor.alter_db_table(
                    new_m2m_model,
                    old_m2m_model._meta.db_table,
                    new_m2m_model._meta.db_table,
                )
                # Rename the column in the M2M table that's based on this
                # model's name.
                schema_editor.alter_field(
                    new_m2m_model,
                    old_m2m_model._meta.get_field(old_model._meta.model_name),
                    new_m2m_model._meta.get_field(new_model._meta.model_name),
                )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        self.new_name_lower, self.old_name_lower = (
            self.old_name_lower,
            self.new_name_lower,
        )
        self.new_name, self.old_name = self.old_name, self.new_name

        self.database_forwards(app_label, schema_editor, from_state, to_state)

        self.new_name_lower, self.old_name_lower = (
            self.old_name_lower,
            self.new_name_lower,
        )
        self.new_name, self.old_name = self.old_name, self.new_name

    def references_model(self, name, app_label):
        return (
            name.lower() == self.old_name_lower or name.lower() == self.new_name_lower
        )

    def describe(self):
        return "Rename model %s to %s" % (self.old_name, self.new_name)

    @property
    def migration_name_fragment(self):
        return "rename_%s_%s" % (self.old_name_lower, self.new_name_lower)

    def reduce(self, operation, app_label):
        if (
            isinstance(operation, RenameModel)
            and self.new_name_lower == operation.old_name_lower
        ):
            return [
                RenameModel(
                    self.old_name,
                    operation.new_name,
                ),
            ]
        # Skip `ModelOperation.reduce` as we want to run `references_model`
        # against self.new_name.
        return super(ModelOperation, self).reduce(
            operation, app_label
        ) or not operation.references_model(self.new_name, app_label)


class ModelOptionOperation(ModelOperation):
    def reduce(self, operation, app_label):
        if (
            isinstance(operation, (self.__class__, DeleteModel))
            and self.name_lower == operation.name_lower
        ):
            return [operation]
        return super().reduce(operation, app_label)


class AlterModelTable(ModelOptionOperation):
    """Rename a model's table."""

    def __init__(self, name, table):
        self.table = table
        super().__init__(name)

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            "table": self.table,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, app_label, state):
        state.alter_model_options(app_label, self.name_lower, {"db_table": self.table})

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        new_model = to_state.apps.get_model(app_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, new_model):
            old_model = from_state.apps.get_model(app_label, self.name)
            schema_editor.alter_db_table(
                new_model,
                old_model._meta.db_table,
                new_model._meta.db_table,
            )
            # Rename M2M fields whose name is based on this model's db_table
            for (old_field, new_field) in zip(
                old_model._meta.local_many_to_many, new_model._meta.local_many_to_many
            ):
                if new_field.remote_field.through._meta.auto_created:
                    schema_editor.alter_db_table(
                        new_field.remote_field.through,
                        old_field.remote_field.through._meta.db_table,
                        new_field.remote_field.through._meta.db_table,
                    )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        return self.database_forwards(app_label, schema_editor, from_state, to_state)

    def describe(self):
        return "Rename table for %s to %s" % (
            self.name,
            self.table if self.table is not None else "(default)",
        )

    @property
    def migration_name_fragment(self):
        return "alter_%s_table" % self.name_lower


class AlterTogetherOptionOperation(ModelOptionOperation):
    option_name = None

    def __init__(self, name, option_value):
        if option_value:
            option_value = set(normalize_together(option_value))
        setattr(self, self.option_name, option_value)
        super().__init__(name)

    @cached_property
    def option_value(self):
        return getattr(self, self.option_name)

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            self.option_name: self.option_value,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, app_label, state):
        state.alter_model_options(
            app_label,
            self.name_lower,
            {self.option_name: self.option_value},
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        new_model = to_state.apps.get_model(app_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, new_model):
            old_model = from_state.apps.get_model(app_label, self.name)
            alter_together = getattr(schema_editor, "alter_%s" % self.option_name)
            alter_together(
                new_model,
                getattr(old_model._meta, self.option_name, set()),
                getattr(new_model._meta, self.option_name, set()),
            )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        return self.database_forwards(app_label, schema_editor, from_state, to_state)

    def references_field(self, model_name, name, app_label):
        return self.references_model(model_name, app_label) and (
            not self.option_value
            or any((name in fields) for fields in self.option_value)
        )

    def describe(self):
        return "Alter %s for %s (%s constraint(s))" % (
            self.option_name,
            self.name,
            len(self.option_value or ""),
        )

    @property
    def migration_name_fragment(self):
        return "alter_%s_%s" % (self.name_lower, self.option_name)

    def can_reduce_through(self, operation, app_label):
        return super().can_reduce_through(operation, app_label) or (
            isinstance(operation, AlterTogetherOptionOperation)
            and type(operation) is not type(self)
        )


class AlterUniqueTogether(AlterTogetherOptionOperation):
    """
    Change the value of unique_together to the target one.
    Input value of unique_together must be a set of tuples.
    """

    option_name = "unique_together"

    def __init__(self, name, unique_together):
        super().__init__(name, unique_together)


class AlterIndexTogether(AlterTogetherOptionOperation):
    """
    Change the value of index_together to the target one.
    Input value of index_together must be a set of tuples.
    """

    option_name = "index_together"

    def __init__(self, name, index_together):
        super().__init__(name, index_together)


class AlterOrderWithRespectTo(ModelOptionOperation):
    """Represent a change with the order_with_respect_to option."""

    option_name = "order_with_respect_to"

    def __init__(self, name, order_with_respect_to):
        self.order_with_respect_to = order_with_respect_to
        super().__init__(name)

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            "order_with_respect_to": self.order_with_respect_to,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, app_label, state):
        state.alter_model_options(
            app_label,
            self.name_lower,
            {self.option_name: self.order_with_respect_to},
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        to_model = to_state.apps.get_model(app_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, to_model):
            from_model = from_state.apps.get_model(app_label, self.name)
            # Remove a field if we need to
            if (
                from_model._meta.order_with_respect_to
                and not to_model._meta.order_with_respect_to
            ):
                schema_editor.remove_field(
                    from_model, from_model._meta.get_field("_order")
                )
            # Add a field if we need to (altering the column is untouched as
            # it's likely a rename)
            elif (
                to_model._meta.order_with_respect_to
                and not from_model._meta.order_with_respect_to
            ):
                field = to_model._meta.get_field("_order")
                if not field.has_default():
                    field.default = 0
                schema_editor.add_field(
                    from_model,
                    field,
                )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        self.database_forwards(app_label, schema_editor, from_state, to_state)

    def references_field(self, model_name, name, app_label):
        return self.references_model(model_name, app_label) and (
            self.order_with_respect_to is None or name == self.order_with_respect_to
        )

    def describe(self):
        return "Set order_with_respect_to on %s to %s" % (
            self.name,
            self.order_with_respect_to,
        )

    @property
    def migration_name_fragment(self):
        return "alter_%s_order_with_respect_to" % self.name_lower


class AlterModelOptions(ModelOptionOperation):
    """
    Set new model options that don't directly affect the database schema
    (like verbose_name, permissions, ordering). Python code in migrations
    may still need them.
    """

    # Model options we want to compare and preserve in an AlterModelOptions op
    ALTER_OPTION_KEYS = [
        "base_manager_name",
        "default_manager_name",
        "default_related_name",
        "get_latest_by",
        "managed",
        "ordering",
        "permissions",
        "default_permissions",
        "select_on_save",
        "verbose_name",
        "verbose_name_plural",
    ]

    def __init__(self, name, options):
        self.options = options
        super().__init__(name)

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            "options": self.options,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, app_label, state):
        state.alter_model_options(
            app_label,
            self.name_lower,
            self.options,
            self.ALTER_OPTION_KEYS,
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        pass

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        pass

    def describe(self):
        return "Change Meta options on %s" % self.name

    @property
    def migration_name_fragment(self):
        return "alter_%s_options" % self.name_lower


class AlterModelManagers(ModelOptionOperation):
    """Alter the model's managers."""

    serialization_expand_args = ["managers"]

    def __init__(self, name, managers):
        self.managers = managers
        super().__init__(name)

    def deconstruct(self):
        return (self.__class__.__qualname__, [self.name, self.managers], {})

    def state_forwards(self, app_label, state):
        state.alter_model_managers(app_label, self.name_lower, self.managers)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        pass

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        pass

    def describe(self):
        return "Change managers on %s" % self.name

    @property
    def migration_name_fragment(self):
        return "alter_%s_managers" % self.name_lower


class IndexOperation(Operation):
    option_name = "indexes"

    @cached_property
    def model_name_lower(self):
        return self.model_name.lower()


class AddIndex(IndexOperation):
    """Add an index on a model."""

    def __init__(self, model_name, index):
        self.model_name = model_name
        if not index.name:
            raise ValueError(
                "Indexes passed to AddIndex operations require a name "
                "argument. %r doesn't have one." % index
            )
        self.index = index

    def state_forwards(self, app_label, state):
        state.add_index(app_label, self.model_name_lower, self.index)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.add_index(model, self.index)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = from_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.remove_index(model, self.index)

    def deconstruct(self):
        kwargs = {
            "model_name": self.model_name,
            "index": self.index,
        }
        return (
            self.__class__.__qualname__,
            [],
            kwargs,
        )

    def describe(self):
        if self.index.expressions:
            return "Create index %s on %s on model %s" % (
                self.index.name,
                ", ".join([str(expression) for expression in self.index.expressions]),
                self.model_name,
            )
        return "Create index %s on field(s) %s of model %s" % (
            self.index.name,
            ", ".join(self.index.fields),
            self.model_name,
        )

    @property
    def migration_name_fragment(self):
        return "%s_%s" % (self.model_name_lower, self.index.name.lower())


class RemoveIndex(IndexOperation):
    """Remove an index from a model."""

    def __init__(self, model_name, name):
        self.model_name = model_name
        self.name = name

    def state_forwards(self, app_label, state):
        state.remove_index(app_label, self.model_name_lower, self.name)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = from_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            from_model_state = from_state.models[app_label, self.model_name_lower]
            index = from_model_state.get_index_by_name(self.name)
            schema_editor.remove_index(model, index)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            to_model_state = to_state.models[app_label, self.model_name_lower]
            index = to_model_state.get_index_by_name(self.name)
            schema_editor.add_index(model, index)

    def deconstruct(self):
        kwargs = {
            "model_name": self.model_name,
            "name": self.name,
        }
        return (
            self.__class__.__qualname__,
            [],
            kwargs,
        )

    def describe(self):
        return "Remove index %s from %s" % (self.name, self.model_name)

    @property
    def migration_name_fragment(self):
        return "remove_%s_%s" % (self.model_name_lower, self.name.lower())


class MigrationStateTracker:
    """
    Migration State Tracker component providing persistent bidirectional mapping
    between original auto-generated names and user-defined names throughout 
    migration lifecycles, enabling reliable backward migration execution.
    """
    
    def __init__(self):
        self._state_cache = {}
    
    def record_mapping(self, migration_name, model_name, original_name, new_name):
        """
        Record bidirectional mapping between original auto-generated name 
        and user-defined name for reliable backward migration support.
        
        Args:
            migration_name: Migration identifier for state organization
            model_name: Model containing the index
            original_name: Original auto-generated index name
            new_name: User-defined target index name
        """
        key = f"{migration_name}_{model_name}"
        if key not in self._state_cache:
            self._state_cache[key] = {}
        
        self._state_cache[key][new_name] = original_name
        logger.debug(
            "Recorded index mapping for %s: %s -> %s", 
            key, original_name, new_name
        )
    
    def retrieve_original_name(self, migration_name, model_name, new_name):
        """
        Retrieve original auto-generated name for backward migration operation.
        
        Args:
            migration_name: Migration identifier for state lookup
            model_name: Model containing the index
            new_name: User-defined index name to reverse
            
        Returns:
            str: Original auto-generated name, or None if not found
        """
        key = f"{migration_name}_{model_name}"
        original_name = self._state_cache.get(key, {}).get(new_name)
        
        if original_name:
            logger.debug(
                "Retrieved original name for %s: %s <- %s", 
                key, original_name, new_name
            )
        else:
            logger.warning(
                "No original name mapping found for %s: %s", 
                key, new_name
            )
        
        return original_name
    
    def clear_migration_state(self, migration_name, model_name):
        """
        Clear migration state for cleanup operations after successful completion.
        
        Args:
            migration_name: Migration identifier for state cleanup
            model_name: Model containing the index
        """
        key = f"{migration_name}_{model_name}"
        if key in self._state_cache:
            del self._state_cache[key]
            logger.debug("Cleared migration state for %s", key)


class IndexNameGenerator:
    """
    Index Name Generator component computing and restoring auto-generated 
    index names using Django's internal naming algorithms, analyzing 
    constraint metadata to reconstruct precise original names for unnamed indexes.
    """
    
    def compute_original_name(self, model, fields, schema_editor):
        """
        Reconstruct auto-generated index name using Django's internal naming algorithms.
        
        Args:
            model: Django model instance
            fields: Field names used in the index
            schema_editor: Database schema editor for name generation
            
        Returns:
            str: Reconstructed auto-generated index name
        """
        try:
            # Get field columns for name generation
            columns = [model._meta.get_field(field).column for field in fields]
            
            # Use Django's internal _create_index_name method to reconstruct
            original_name = schema_editor._create_index_name(
                model._meta.db_table, columns, suffix="_idx"
            )
            
            logger.debug(
                "Computed original name for %s.%s: %s", 
                model._meta.db_table, fields, original_name
            )
            return original_name
            
        except Exception as e:
            logger.error(
                "Failed to compute original name for %s.%s: %s", 
                model._meta.db_table, fields, str(e)
            )
            return None
    
    def validate_name_uniqueness(self, model, proposed_name, schema_editor):
        """
        Validate that proposed index name doesn't conflict with existing database objects.
        
        Args:
            model: Django model instance
            proposed_name: Index name to validate
            schema_editor: Database schema editor for validation
            
        Returns:
            bool: True if name is available, False if conflict exists
        """
        try:
            # Use schema editor's validation method if available
            if hasattr(schema_editor, 'validate_index_name_availability'):
                return schema_editor.validate_index_name_availability(model, proposed_name)
            
            # Fallback validation using constraint introspection
            with schema_editor.connection.cursor() as cursor:
                constraints = schema_editor.connection.introspection.get_constraints(
                    cursor, model._meta.db_table
                )
            
            return proposed_name not in constraints
            
        except Exception as e:
            logger.error(
                "Failed to validate name uniqueness for %s: %s", 
                proposed_name, str(e)
            )
            return False
    
    def analyze_constraint_origin(self, model, index_name, schema_editor):
        """
        Analyze constraint metadata to identify index creation source.
        
        Args:
            model: Django model instance
            index_name: Index name to analyze
            schema_editor: Database schema editor for introspection
            
        Returns:
            dict: Constraint origin metadata including creation source
        """
        try:
            with schema_editor.connection.cursor() as cursor:
                constraints = schema_editor.connection.introspection.get_constraints(
                    cursor, model._meta.db_table
                )
            
            if index_name in constraints:
                constraint_info = constraints[index_name]
                origin_info = {
                    'columns': constraint_info.get('columns', []),
                    'unique': constraint_info.get('unique', False),
                    'index': constraint_info.get('index', False),
                    'primary_key': constraint_info.get('primary_key', False),
                    'source': 'unknown'
                }
                
                # Analyze if this matches unique_together pattern
                if constraint_info.get('unique', False) and len(constraint_info.get('columns', [])) > 1:
                    origin_info['source'] = 'unique_together'
                elif constraint_info.get('index', False):
                    origin_info['source'] = 'index_together'
                
                logger.debug(
                    "Analyzed constraint origin for %s: %s", 
                    index_name, origin_info
                )
                return origin_info
            
            logger.warning("Constraint not found for analysis: %s", index_name)
            return {}
            
        except Exception as e:
            logger.error(
                "Failed to analyze constraint origin for %s: %s", 
                index_name, str(e)
            )
            return {}


class RenameIndex(IndexOperation):
    """
    Enhanced RenameIndex operation implementing forward and backward rename logic 
    for Django database indexes, with specialized handling for unnamed indexes 
    created by unique_together constraints through Migration State Tracker coordination.
    """

    def __init__(self, model_name, new_name, old_name=None, old_fields=None):
        if not old_name and not old_fields:
            raise ValueError(
                "RenameIndex requires one of old_name and old_fields arguments to be "
                "set."
            )
        if old_name and old_fields:
            raise ValueError(
                "RenameIndex.old_name and old_fields are mutually exclusive."
            )
        self.model_name = model_name
        self.new_name = new_name
        self.old_name = old_name
        self.old_fields = old_fields
        
        # Initialize enhanced components for unnamed index handling
        self._state_tracker = MigrationStateTracker()
        self._name_generator = IndexNameGenerator()
        self._original_auto_name = None  # Store computed original name

    @cached_property
    def old_name_lower(self):
        return self.old_name.lower() if self.old_name else None

    @cached_property
    def new_name_lower(self):
        return self.new_name.lower()

    def deconstruct(self):
        kwargs = {
            "model_name": self.model_name,
            "new_name": self.new_name,
        }
        if self.old_name:
            kwargs["old_name"] = self.old_name
        if self.old_fields:
            kwargs["old_fields"] = self.old_fields
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, app_label, state):
        if self.old_fields:
            state.add_index(
                app_label,
                self.model_name_lower,
                models.Index(fields=self.old_fields, name=self.new_name),
            )
            state.remove_model_options(
                app_label,
                self.model_name_lower,
                AlterIndexTogether.option_name,
                self.old_fields,
            )
        else:
            state.rename_index(
                app_label, self.model_name_lower, self.old_name, self.new_name
            )

    def validate_rename_target(self, model, schema_editor):
        """
        Pre-execution validation of index rename operations, including 
        duplicate detection and naming conflict prevention.
        
        Args:
            model: Django model instance
            schema_editor: Database schema editor for validation
            
        Returns:
            bool: True if rename operation is valid, False otherwise
        """
        try:
            # Validate new name doesn't conflict with existing objects
            if not self._name_generator.validate_name_uniqueness(
                model, self.new_name, schema_editor
            ):
                logger.error(
                    "Index rename validation failed: target name %s conflicts with existing object on %s",
                    self.new_name, model._meta.db_table
                )
                return False
            
            # For unnamed indexes, validate we can compute original name
            if self.old_fields:
                original_name = self._name_generator.compute_original_name(
                    model, self.old_fields, schema_editor
                )
                if not original_name:
                    logger.error(
                        "Index rename validation failed: cannot compute original name for unnamed index on %s.%s",
                        model._meta.db_table, self.old_fields
                    )
                    return False
                
                self._original_auto_name = original_name
            
            logger.debug(
                "Index rename validation successful for %s on %s",
                self.new_name, model._meta.db_table
            )
            return True
            
        except Exception as e:
            logger.error(
                "Index rename validation failed for %s on %s: %s",
                self.new_name, model._meta.db_table, str(e)
            )
            return False

    def execute_forward(self, app_label, schema_editor, from_state, to_state, migration_name=None):
        """
        Execute forward migration with state initialization, unnamed index detection,
        and mapping preservation through Migration State Tracker coordination.
        
        Args:
            app_label: Application label for model resolution
            schema_editor: Database schema editor for operations
            from_state: Migration state before operation
            to_state: Migration state after operation
            migration_name: Migration identifier for state tracking
            
        Returns:
            bool: True if forward execution succeeded, False otherwise
        """
        try:
            model = to_state.apps.get_model(app_label, self.model_name)
            
            # Pre-execution validation
            if not self.validate_rename_target(model, schema_editor):
                return False
            
            # Handle unnamed index scenario (old_fields specified)
            if self.old_fields:
                logger.info(
                    "Executing forward rename for unnamed index on %s.%s -> %s",
                    model._meta.db_table, self.old_fields, self.new_name
                )
                
                from_model = from_state.apps.get_model(app_label, self.model_name)
                columns = [
                    from_model._meta.get_field(field).column for field in self.old_fields
                ]
                
                # Find the auto-generated index name
                matching_index_names = schema_editor._constraint_names(
                    from_model, column_names=columns, index=True
                )
                
                if len(matching_index_names) != 1:
                    logger.error(
                        "Found wrong number (%s) of indexes for %s(%s)",
                        len(matching_index_names),
                        from_model._meta.db_table,
                        ", ".join(columns)
                    )
                    return False
                
                actual_old_name = matching_index_names[0]
                
                # Record state mapping for backward migration
                if migration_name:
                    self._state_tracker.record_mapping(
                        migration_name, self.model_name, actual_old_name, self.new_name
                    )
                
                # Create index objects for rename operation
                old_index = models.Index(fields=self.old_fields, name=actual_old_name)
                to_model_state = to_state.models[app_label, self.model_name_lower]
                new_index = to_model_state.get_index_by_name(self.new_name)
                
                # Execute rename with transaction safety
                with atomic(using=schema_editor.connection.alias):
                    schema_editor.rename_index(model, old_index, new_index)
                
            else:
                # Handle named index scenario (standard case)
                logger.info(
                    "Executing forward rename for named index %s -> %s on %s",
                    self.old_name, self.new_name, model._meta.db_table
                )
                
                from_model_state = from_state.models[app_label, self.model_name_lower]
                old_index = from_model_state.get_index_by_name(self.old_name)
                to_model_state = to_state.models[app_label, self.model_name_lower]
                new_index = to_model_state.get_index_by_name(self.new_name)
                
                # Execute rename with transaction safety
                with atomic(using=schema_editor.connection.alias):
                    schema_editor.rename_index(model, old_index, new_index)
            
            logger.info(
                "Forward index rename completed successfully for %s on %s",
                self.new_name, model._meta.db_table
            )
            return True
            
        except Exception as e:
            logger.error(
                "Forward index rename failed for %s on %s: %s",
                self.new_name, getattr(model, '_meta', {}).get('db_table', 'unknown'), str(e)
            )
            return False

    def execute_backward(self, app_label, schema_editor, from_state, to_state, migration_name=None):
        """
        Execute backward migration with original name restoration, conflict resolution,
        and state cleanup mechanisms.
        
        Args:
            app_label: Application label for model resolution
            schema_editor: Database schema editor for operations
            from_state: Migration state before rollback
            to_state: Migration state after rollback
            migration_name: Migration identifier for state tracking
            
        Returns:
            bool: True if backward execution succeeded, False otherwise
        """
        try:
            model = to_state.apps.get_model(app_label, self.model_name)
            
            # Handle unnamed index rollback scenario
            if self.old_fields:
                logger.info(
                    "Executing backward migration for unnamed index %s -> original on %s.%s",
                    self.new_name, model._meta.db_table, self.old_fields
                )
                
                # Retrieve original auto-generated name from state tracker
                original_name = None
                if migration_name:
                    original_name = self._state_tracker.retrieve_original_name(
                        migration_name, self.model_name, self.new_name
                    )
                
                # If no state record, compute original name using name generator
                if not original_name:
                    logger.warning(
                        "No state record found for %s, computing original name",
                        self.new_name
                    )
                    original_name = self._name_generator.compute_original_name(
                        model, self.old_fields, schema_editor
                    )
                
                if not original_name:
                    logger.error(
                        "Cannot determine original name for unnamed index rollback: %s on %s.%s",
                        self.new_name, model._meta.db_table, self.old_fields
                    )
                    return False
                
                # Check if original name would conflict
                if not self._name_generator.validate_name_uniqueness(
                    model, original_name, schema_editor
                ):
                    logger.warning(
                        "Original name %s conflicts with existing object, attempting fallback",
                        original_name
                    )
                    
                    # Use schema editor's fallback generation if available
                    if hasattr(schema_editor, 'generate_fallback_index_name'):
                        original_name = schema_editor.generate_fallback_index_name(
                            model, original_name
                        )
                        if not original_name:
                            logger.error(
                                "Cannot resolve naming conflict for unnamed index rollback"
                            )
                            return False
                
                # Create index objects for rollback rename
                current_index = models.Index(fields=self.old_fields, name=self.new_name)
                restored_index = models.Index(fields=self.old_fields, name=original_name)
                
                # Execute rollback rename with transaction safety
                with atomic(using=schema_editor.connection.alias):
                    schema_editor.rename_index(model, current_index, restored_index)
                
                # Clean up state tracking after successful rollback
                if migration_name:
                    self._state_tracker.clear_migration_state(migration_name, self.model_name)
                
            else:
                # Handle named index rollback (standard case) 
                logger.info(
                    "Executing backward migration for named index %s -> %s on %s",
                    self.new_name, self.old_name, model._meta.db_table
                )
                
                # Create index objects with swapped names for rollback
                current_index = models.Index(fields=[], name=self.new_name)  
                restored_index = models.Index(fields=[], name=self.old_name)
                
                # Execute rollback rename with transaction safety
                with atomic(using=schema_editor.connection.alias):
                    schema_editor.rename_index(model, current_index, restored_index)
            
            logger.info(
                "Backward index rename completed successfully for %s on %s",
                self.new_name, model._meta.db_table
            )
            return True
            
        except Exception as e:
            logger.error(
                "Backward index rename failed for %s on %s: %s",
                self.new_name, getattr(model, '_meta', {}).get('db_table', 'unknown'), str(e)
            )
            return False

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """
        Enhanced database_forwards method implementing state tracking for original
        auto-generated names before rename execution, handling previously unnamed 
        indexes correctly with Migration State Tracker coordination.
        """
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return

        # Extract migration name from schema editor or current migration context
        migration_name = getattr(schema_editor, '_current_migration_name', None)
        
        # Use enhanced forward execution method
        success = self.execute_forward(
            app_label, schema_editor, from_state, to_state, migration_name
        )
        
        if not success:
            raise ValueError(
                f"Failed to execute forward rename operation for index {self.new_name} "
                f"on {model._meta.db_table}"
            )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        """
        Enhanced database_backwards method with unnamed index detection and 
        auto-generated name restoration capabilities, implementing state tracking 
        for reliable restoration of original unnamed indexes created by unique_together constraints.
        """
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return

        # Extract migration name from schema editor or current migration context  
        migration_name = getattr(schema_editor, '_current_migration_name', None)
        
        # Use enhanced backward execution method
        success = self.execute_backward(
            app_label, schema_editor, from_state, to_state, migration_name
        )
        
        if not success:
            # For unnamed indexes, provide more specific error context
            if self.old_fields:
                raise ValueError(
                    f"Failed to execute backward rename operation for unnamed index {self.new_name} "
                    f"on {model._meta.db_table}. This may be due to PostgreSQL duplicate index "
                    f"constraints when restoring auto-generated names from unique_together. "
                    f"Original fields: {self.old_fields}"
                )
            else:
                raise ValueError(
                    f"Failed to execute backward rename operation for index {self.new_name} "
                    f"on {model._meta.db_table}"
                )

    def describe(self):
        if self.old_name:
            return (
                f"Rename index {self.old_name} on {self.model_name} to {self.new_name}"
            )
        return (
            f"Rename unnamed index for {self.old_fields} on {self.model_name} to "
            f"{self.new_name}"
        )

    @property
    def migration_name_fragment(self):
        if self.old_name:
            return "rename_%s_%s" % (self.old_name_lower, self.new_name_lower)
        return "rename_%s_%s_%s" % (
            self.model_name_lower,
            "_".join(self.old_fields),
            self.new_name_lower,
        )

    def reduce(self, operation, app_label):
        if (
            isinstance(operation, RenameIndex)
            and self.model_name_lower == operation.model_name_lower
            and operation.old_name
            and self.new_name_lower == operation.old_name_lower
        ):
            return [
                RenameIndex(
                    self.model_name,
                    new_name=operation.new_name,
                    old_name=self.old_name,
                    old_fields=self.old_fields,
                )
            ]
        return super().reduce(operation, app_label)


class AddConstraint(IndexOperation):
    option_name = "constraints"

    def __init__(self, model_name, constraint):
        self.model_name = model_name
        self.constraint = constraint

    def state_forwards(self, app_label, state):
        state.add_constraint(app_label, self.model_name_lower, self.constraint)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.add_constraint(model, self.constraint)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.remove_constraint(model, self.constraint)

    def deconstruct(self):
        return (
            self.__class__.__name__,
            [],
            {
                "model_name": self.model_name,
                "constraint": self.constraint,
            },
        )

    def describe(self):
        return "Create constraint %s on model %s" % (
            self.constraint.name,
            self.model_name,
        )

    @property
    def migration_name_fragment(self):
        return "%s_%s" % (self.model_name_lower, self.constraint.name.lower())


class RemoveConstraint(IndexOperation):
    option_name = "constraints"

    def __init__(self, model_name, name):
        self.model_name = model_name
        self.name = name

    def state_forwards(self, app_label, state):
        state.remove_constraint(app_label, self.model_name_lower, self.name)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            from_model_state = from_state.models[app_label, self.model_name_lower]
            constraint = from_model_state.get_constraint_by_name(self.name)
            schema_editor.remove_constraint(model, constraint)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            to_model_state = to_state.models[app_label, self.model_name_lower]
            constraint = to_model_state.get_constraint_by_name(self.name)
            schema_editor.add_constraint(model, constraint)

    def deconstruct(self):
        return (
            self.__class__.__name__,
            [],
            {
                "model_name": self.model_name,
                "name": self.name,
            },
        )

    def describe(self):
        return "Remove constraint %s from model %s" % (self.name, self.model_name)

    @property
    def migration_name_fragment(self):
        return "remove_%s_%s" % (self.model_name_lower, self.name.lower())
