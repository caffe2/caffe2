"""
Defines a minimal set of data types that allow to represent datasets with
arbitrary nested structure, including objects of variable length, such as
maps and lists.

This defines a columnar storage format for such datasets on top of caffe2
tensors. In terms of capacity of representation, it can represent most of
the data types supported by Parquet, ORC, DWRF file formats.

See comments in operator_test/dataset_ops_test.py for a example and
walkthrough on how to use schema to store and iterate through a structured
in-memory dataset.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import logging
import numpy as np
from caffe2.python import core
from caffe2.python import workspace
from caffe2.python.core import ScopedBlobReference, BlobReference
from collections import OrderedDict, namedtuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _join_field_name(prefix, suffix):
    if prefix and suffix:
        return '{}:{}'.format(prefix, suffix)
    elif prefix:
        return prefix
    elif suffix:
        return suffix
    else:
        return ''


def _normalize_field(field_or_type_or_blob, keep_blobs=True):
    """Clones/normalizes a field before adding it to a container."""
    if isinstance(field_or_type_or_blob, Field):
        return field_or_type_or_blob.clone(keep_blobs=keep_blobs)
    elif type(field_or_type_or_blob) in (type, np.dtype):
        return Scalar(dtype=field_or_type_or_blob)
    else:
        return Scalar(blob=field_or_type_or_blob)

FeatureSpec = namedtuple(
    'FeatureSpec',
    ['feature_type', 'feature_names', 'feature_ids', 'feature_is_request_only'])
FeatureSpec.__new__.__defaults__ = (None, None, None, None)


class Metadata(namedtuple('Metadata', ['categorical_limit', 'expected_value',
                                       'feature_specs'])):
    """Represents additional information associated with a scalar in schema.

    `categorical_limit` - for fields of integral type that are guaranteed to be
    non-negative it specifies the maximum possible value plus one. It's often
    used as a size of an embedding table.

    `expected_value` - anticipated average value of elements in the field.
    Usually makes sense for length fields of lists.

    `feature_specs` - information about the features that contained in this
    field. For example if field have more then 1 feature it can have list of
    feature names contained in this field."""
    __slots__ = ()
Metadata.__new__.__defaults__ = (None, None, None)


class Field(object):
    """Represents an abstract field type in a dataset.
    """

    def __init__(self, children):
        """Derived classes must call this after their initialization."""
        self._parent = (None, 0)
        offset = 0
        self._field_offsets = []
        for child in children:
            self._field_offsets.append(offset)
            offset += len(child.field_names())
        self._field_offsets.append(offset)

    def clone_schema(self):
        return self.clone(keep_blobs=False)

    def field_names(self):
        """Return the children field names for this field."""
        raise NotImplementedError('Field is an abstract class.')

    def field_types(self):
        """Return the numpy.dtype for each of the children fields."""
        raise NotImplementedError('Field is an abstract class.')

    def field_metadata(self):
        """Return the Metadata for each of the children fields."""
        raise NotImplementedError('Field is an abstract class.')

    def field_blobs(self):
        """Return the list of blobs with contents for this Field.
        Values can either be all numpy.ndarray or BlobReference.
        If any of the fields doens't have a blob, throws.
        """
        raise NotImplementedError('Field is an abstract class.')

    def all_scalars(self):
        """Return the list of all Scalar instances in the Field.
        The order is the same as for field_names() or field_blobs()"""
        raise NotImplementedError('Field is an abstract class.')

    def has_blobs(self):
        """Return True if every scalar of this field has blobs."""
        raise NotImplementedError('Field is an abstract class.')

    def clone(self, keep_blobs=True):
        """Clone this Field along with its children."""
        raise NotImplementedError('Field is an abstract class.')

    def _set_parent(self, parent, relative_id):
        self._parent = (parent, relative_id)

    def slice(self):
        """
        Returns a slice representing the range of field ids that belong to
        this field. This slice can be used to index a list of fields.

        E.g.:

        >>> s = Struct(
        >>>     ('a', Scalar()),
        >>>     ('b', Struct(
        >>>         ('b1', Scalar()),
        >>>         ('b2', Scalar()),
        >>>     )),
        >>>     ('c', Scalar()),
        >>> )
        >>> field_data = ['da', 'db1', 'db2', 'dc']
        >>> field_data[s.b.split()]
        ['db1', 'db2']
        """
        base_id = self._child_base_id()
        return slice(base_id, base_id + len(self.field_names()))

    def _child_base_id(self, child_index=None):
        """Get the base id of the given child"""
        p, i = self._parent
        pos = 0 if child_index is None else self._field_offsets[child_index]
        if p:
            pos += p._child_base_id(i)
        return pos

    def __eq__(self, other):
        """Equivalance of two schemas"""
        return ((self.field_names() == other.field_names()) and
                (self.field_types() == other.field_types()) and
                (self.field_metadata() == other.field_metadata()))


class List(Field):
    """Represents a variable-length list.

    Values of a list can also be complex fields such as Lists and Structs.
    In addition to the fields exposed by its `values` field, a List exposes an
    additional `lengths` field, which will contain the size of each list under
    the parent domain.
    """

    def __init__(self, values, lengths_blob=None):
        self.lengths = Scalar(np.int32, lengths_blob)
        self._items = _normalize_field(values)
        self.lengths._set_parent(self, 0)
        self._items._set_parent(self, 1)
        Field.__init__(self, [self.lengths, self._items])

    def field_names(self):
        value_fields = self._items.field_names()
        return (
            ['lengths'] +
            [_join_field_name('values', v) for v in value_fields])

    def field_types(self):
        return self.lengths.field_types() + self._items.field_types()

    def field_metadata(self):
        return self.lengths.field_metadata() + self._items.field_metadata()

    def field_blobs(self):
        return self.lengths.field_blobs() + self._items.field_blobs()

    def all_scalars(self):
        return self.lengths.all_scalars() + self._items.all_scalars()

    def has_blobs(self):
        return self.lengths.has_blobs() and self._items.has_blobs()

    def clone(self, keep_blobs=True):
        return List(self._items, self.lengths._blob if keep_blobs else None)

    def __getattr__(self, item):
        """If the value of this list is a struct,
        allow to instrospect directly into its fields."""
        if item.startswith('__'):
            raise AttributeError(item)
        if isinstance(self._items, Struct):
            return getattr(self._items, item)
        elif item == 'value' or item == 'items':
            return self._items
        else:
            raise AttributeError('Field not found in list: %s.' % item)


class Struct(Field):
    """Represents a named list of fields sharing the same domain.
    """

    def __init__(self, *fields):
        for field in fields:
            assert len(field) == 2
            assert field[0], 'Field names cannot be empty'
            assert field[0] != 'lengths', (
                'Struct cannot contain a field named `lengths`.')
        fields = [(name, _normalize_field(field)) for name, field in fields]
        for id, (name, field) in enumerate(fields):
            field._set_parent(self, id)
        self.fields = OrderedDict(fields)
        Field.__init__(self, self.fields.values())

    def get_children(self):
        return self.fields.items()

    def field_names(self):
        names = []
        for name, field in self.fields.items():
            names += [_join_field_name(name, f) for f in field.field_names()]
        return names

    def field_types(self):
        types = []
        for name, field in self.fields.items():
            types += field.field_types()
        return types

    def field_metadata(self):
        metadata = []
        for name, field in self.fields.items():
            metadata += field.field_metadata()
        return metadata

    def field_blobs(self):
        blobs = []
        for name, field in self.fields.items():
            blobs += field.field_blobs()
        return blobs

    def all_scalars(self):
        scalars = []
        for name, field in self.fields.items():
            scalars += field.all_scalars()
        return scalars

    def has_blobs(self):
        return all(field.has_blobs() for field in self.fields.values())

    def clone(self, keep_blobs=True):
        normalized_fields = [
            (k, _normalize_field(v, keep_blobs=keep_blobs))
            for k, v in self.fields.items()
        ]
        return Struct(*normalized_fields)

    def __len__(self):
        return len(self.fields)

    def __getitem__(self, item):
        if isinstance(item, list) or isinstance(item, tuple):
            return Struct(*[(
                self.fields.keys()[k] if isinstance(k, int) else k, self[k])
                for k in item])
        elif isinstance(item, int):
            return self.fields.values()[item]
        else:
            return self.fields[item]

    def __getattr__(self, item):
        if item.startswith('__'):
            raise AttributeError(item)
        try:
            return self.__dict__['fields'][item]
        except KeyError:
            raise AttributeError(item)


class Scalar(Field):
    """Represents a typed scalar or tensor of fixed shape.

    A Scalar is a leaf in a schema tree, translating to exactly one tensor in
    the dataset's underlying storage.

    Usually, the tensor storing the actual values of this field is a 1D tensor,
    representing a series of values in its domain. It is possible however to
    have higher rank values stored as a Scalar, as long as all entries have
    the same shape.

    E.g.:

        Scalar(np.float64)

            Scalar field of type float32. Caffe2 will expect readers and
            datasets to expose it as a 1D tensor of doubles (vector), where
            the size of the vector is determined by this fields' domain.

        Scalar((np.int32, 5))

            Tensor field of type int32. Caffe2 will expect readers and
            datasets to implement it as a 2D tensor (matrix) of shape (L, 5),
            where L is determined by this fields' domain.

        Scalar((str, (10, 20)))

            Tensor field of type str. Caffe2 will expect readers and
            datasets to implement it as a 3D tensor of shape (L, 10, 20),
            where L is determined by this fields' domain.

    If the field type is unknown at construction time, call Scalar(), that will
    default to np.void as its dtype.

    It is an error to pass a structured dtype to Scalar, since it would contain
    more than one field. Instead, use from_dtype, which will construct
    a nested `Struct` field reflecting the given dtype's structure.

    A Scalar can also contain a blob, which represents the value of this
    Scalar. A blob can be either a numpy.ndarray, in which case it contain the
    actual contents of the Scalar, or a BlobReference, which represents a
    blob living in a caffe2 Workspace. If blob of different types are passed,
    a conversion to numpy.ndarray is attempted.
    """

    def __init__(self, dtype=None, blob=None, metadata=None):
        self._metadata = None
        self.set(dtype, blob, metadata)
        Field.__init__(self, [])

    def field_names(self):
        return ['']

    def field_type(self):
        return self.dtype

    def field_types(self):
        return [self.dtype]

    def field_metadata(self):
        return [self._metadata]

    def has_blobs(self):
        return self._blob is not None

    def field_blobs(self):
        assert self._blob is not None, 'Value is not set for this field.'
        return [self._blob]

    def all_scalars(self):
        return [self]

    def clone(self, keep_blobs=True):
        return Scalar(
            dtype=self._original_dtype,
            blob=self._blob if keep_blobs else None,
            metadata=self._metadata)

    def get(self):
        """Gets the current blob of this Scalar field."""
        assert self._blob is not None, 'Value is not set for this field.'
        return self._blob

    def __call__(self):
        """Shortcut for self.get()"""
        return self.get()

    @property
    def metadata(self):
        return self._metadata

    def set_metadata(self, value):
        assert isinstance(value, Metadata), \
            'metadata must be Metadata, got {}'.format(type(value))
        self._metadata = value
        self._validate_metadata()

    def _validate_metadata(self):
        if self._metadata is None:
            return
        if (self._metadata.categorical_limit is not None and
                self.dtype is not None):
            assert np.issubdtype(self.dtype, np.integer), \
                "`categorical_limit` can be specified only in integral " + \
                "fields but got {}".format(self.dtype)

    def set_value(self, blob):
        """Sets only the blob field still validating the existing dtype"""
        self.set(dtype=self._original_dtype, blob=blob)

    def set(self, dtype=None, blob=None, metadata=None):
        """Set the type and/or blob of this scalar. See __init__ for details.

        Args:
            dtype: can be any numpy type. If not provided and `blob` is
                   provided, it will be inferred. If no argument is provided,
                   this Scalar will be of type np.void.
            blob:  if provided, can be either a BlobReference or a
                   numpy.ndarray. If a value of different type is passed,
                   a conversion to numpy.ndarray is attempted. Strings aren't
                   accepted, since they can be ambiguous. If you want to pass
                   a string, to either BlobReference(blob) or np.array(blob).
            metadata: optional instance of Metadata, if provided overrides
                      the metadata information of the scalar
        """
        if blob is not None and isinstance(blob, core.basestring):
            raise ValueError(
                'Passing str blob to Scalar.set() is ambiguous. '
                'Do either set(blob=np.array(blob)) or '
                'set(blob=BlobReference(blob))')

        self._original_dtype = dtype
        if dtype is not None:
            dtype = np.dtype(dtype)
        # If blob is not None and it is not a BlobReference, we assume that
        # it is actual tensor data, so we will try to cast it to an numpy array.
        if blob is not None and not isinstance(blob, BlobReference):
            if dtype is not None and dtype != np.void:
                blob = np.array(blob, dtype=dtype.base)
                # if array is empty we may need to reshape a little
                if blob.size == 0:
                    blob = blob.reshape((0,) + dtype.shape)
            else:
                assert isinstance(blob, np.ndarray), (
                    'Invalid blob type: %s' % str(type(blob)))

            # reshape scalars into 1D arrays
            # TODO(azzolini): figure out better way of representing this
            if len(blob.shape) == 0:
                blob = blob.reshape((1,))

            # infer inner shape from the blob given
            # TODO(dzhulgakov): tweak this to make it work with PackedStruct
            if (len(blob.shape) > 1 and dtype is not None and
                    dtype.base != np.void):
                dtype = np.dtype((dtype.base, blob.shape[1:]))
        # if we were still unable to infer the dtype
        if dtype is None:
            dtype = np.dtype(np.void)
        assert not dtype.fields, (
            'Cannot create Scalar with a structured dtype. ' +
            'Use from_dtype instead.')
        self.dtype = dtype
        self._blob = blob
        if metadata is not None:
            self.set_metadata(metadata)
        self._validate_metadata()

    def set_type(self, dtype):
        self._original_dtype = dtype
        self.dtype = np.dtype(dtype or np.void)
        self._validate_metadata()

    def id(self):
        """
        Return the zero-indexed position of this scalar field in its schema.
        Used in order to index into the field_blob list returned by readers or
        accepted by writers.
        """
        return self._child_base_id()


def Map(keys, values, keys_name='keys', values_name='values',
        lengths_blob=None):
    """A map is a List of Struct containing keys and values fields.
    Optionally, you can provide custom name for the key and value fields.
    """
    return List(
        Struct((keys_name, keys), (values_name, values)),
        lengths_blob=lengths_blob)


def Tuple(*fields):
    """
    Creates a Struct with default, sequential, field names of given types.
    """
    return Struct(*[
        ('field_%d' % i, field) for i, field in enumerate(fields)])


def RawTuple(num_fields):
    """
    Creates a tuple of `num_field` untyped scalars.
    """
    assert isinstance(num_fields, int)
    assert num_fields > 0
    return Tuple(*([np.void] * num_fields))


def from_dtype(dtype, _outer_shape=()):
    """Constructs a Caffe2 schema from the given numpy's dtype.

    Numpy supports scalar, array-like and structured datatypes, as long as
    all the shapes are fixed. This function breaks down the given dtype into
    a Caffe2 schema containing `Struct` and `Scalar` types.

    Fields containing byte offsets are not currently supported.
    """
    if not isinstance(dtype, np.dtype):
        # wrap into a ndtype
        shape = _outer_shape
        dtype = np.dtype((dtype, _outer_shape))
    else:
        # concatenate shapes if necessary
        shape = _outer_shape + dtype.shape
        if shape != dtype.shape:
            dtype = np.dtype((dtype.base, shape))

    if not dtype.fields:
        return Scalar(dtype)

    struct_fields = []
    for name, (fdtype, offset) in dtype.fields:
        assert offset == 0, ('Fields with byte offsets are not supported.')
        struct_fields += (name, from_dtype(fdtype, _outer_shape=shape))
    return Struct(*struct_fields)


class _SchemaNode(object):
    """This is a private class used to represent a Schema Node"""

    def __init__(self, name, type_str=''):
        self.name = name
        self.children = []
        self.type_str = type_str
        self.field = None
        self.col_blob = None

    def add_child(self, name, type_str=''):
        for child in self.children:
            if child.name == name and child.type_str == type_str:
                return child
        child = _SchemaNode(name, type_str)
        self.children.append(child)
        return child

    def get_field(self):

        list_names = ['lengths', 'values']
        map_names = ['lengths', 'keys', 'values']

        if len(self.children) == 0 or self.field is not None:
            assert self.field is not None
            return self.field

        child_names = []
        for child in self.children:
            child_names.append(child.name)

        if (set(child_names) == set(list_names)):
            for child in self.children:
                if child.name == 'values':
                    self.field = List(
                        child.get_field(),
                        lengths_blob=self.children[0].col_blob)
                    self.type_str = "List"
                    return self.field
        elif (set(child_names) == set(map_names)):
            for child in self.children:
                if child.name == 'keys':
                    key_field = child.get_field()
                elif child.name == 'values':
                    values_field = child.get_field()
            self.field = Map(
                key_field,
                values_field,
                lengths_blob=self.children[0].col_blob)
            self.type_str = "Map"
            return self.field

        else:
            struct_fields = []
            for child in self.children:
                if child.field is not None:
                    struct_fields.append((child.name, child.field))
                else:
                    struct_fields.append((child.name, child.get_field()))

            self.field = Struct(*struct_fields)
            self.type_str = "Struct"
            return self.field

    def print_recursively(self):
        for child in self.children:
            child.print_recursively()
        logger.info("Printing node: Name and type")
        logger.info(self.name)
        logger.info(self.type_str)


def from_column_list(col_names, col_types=None, col_blobs=None,
                     col_metadata=None):
    """
    Given a list of names, types, and optionally values, construct a Schema.
    """
    if col_types is None:
        col_types = [None] * len(col_names)
    if col_metadata is None:
        col_metadata = [None] * len(col_names)
    if col_blobs is None:
        col_blobs = [None] * len(col_names)
    assert len(col_names) == len(col_types), (
        'col_names and col_types must have the same length.')
    assert len(col_names) == len(col_metadata), (
        'col_names and col_metadata must have the same length.')
    assert len(col_names) == len(col_blobs), (
        'col_names and col_blobs must have the same length.')
    root = _SchemaNode('root', 'Struct')
    for col_name, col_type, col_blob, col_metadata in zip(
            col_names, col_types, col_blobs, col_metadata):
        columns = col_name.split(':')
        current = root
        for i in range(len(columns)):
            name = columns[i]
            type_str = ''
            field = None
            if i == len(columns) - 1:
                type_str = col_type
                field = Scalar(dtype=col_type, blob=col_blob,
                               metadata=col_metadata)
            next = current.add_child(name, type_str)
            if field is not None:
                next.field = field
                next.col_blob = col_blob
            current = next

    return root.get_field()


def from_blob_list(schema, values):
    """
    Create a schema that clones the given schema, but containing the given
    list of values.
    """
    assert isinstance(schema, Field), 'Argument `schema` must be a Field.'
    if isinstance(values, BlobReference):
        values = [values]
    record = schema.clone_schema()
    scalars = record.all_scalars()
    assert len(scalars) == len(values), (
        'Values must have %d elements, got %d.' % (len(scalars), len(values)))
    for scalar, value in zip(scalars, values):
        scalar.set_value(value)
    return record


def as_record(value):
    if isinstance(value, Field):
        return value
    elif isinstance(value, list) or isinstance(value, tuple):
        is_field_list = all(
            f is tuple and len(f) == 2 and isinstance(f[0], core.basestring)
            for f in value)
        if is_field_list:
            return Struct(*[(k, as_record(v)) for k, v in value])
        else:
            return Tuple(*[as_record(f) for f in value])
    elif isinstance(value, dict):
        return Struct(*[(k, as_record(v)) for k, v in value.items()])
    else:
        return _normalize_field(value)


def FetchRecord(blob_record, ws=None):
    """
    Given a record containing BlobReferences, return a new record with same
    schema, containing numpy arrays, fetched from the current active workspace.
    """
    def fetch(v):
        if ws is None:
            return workspace.FetchBlob(str(v))
        else:
            return ws.blobs[str(v)].fetch()

    assert isinstance(blob_record, Field)
    field_blobs = blob_record.field_blobs()
    assert all(isinstance(v, BlobReference) for v in field_blobs)
    field_arrays = [fetch(value) for value in field_blobs]
    return from_blob_list(blob_record, field_arrays)


def FeedRecord(blob_record, arrays, ws=None):
    """
    Given a Record containing blob_references and arrays, which is either
    a list of numpy arrays or a Record containing numpy arrays, feeds the
    record to the current workspace.
    """
    def feed(b, v):
        if ws is None:
            workspace.FeedBlob(str(b), v)
        else:
            ws.create_blob(str(b))
            ws.blobs[str(b)].feed(v)

    assert isinstance(blob_record, Field)
    field_blobs = blob_record.field_blobs()
    assert all(isinstance(v, BlobReference) for v in field_blobs)
    if isinstance(arrays, Field):
        # TODO: check schema
        arrays = arrays.field_blobs()
    assert len(arrays) == len(field_blobs), (
        'Values must contain exactly %d ndarrays.' % len(field_blobs))
    for blob, array in zip(field_blobs, arrays):
        feed(blob, array)


def NewRecord(net, schema):
    """
    Given a record of np.arrays, create a BlobReference for each one of them,
    returning a record containing BlobReferences. The BlobReferences will be
    added as ExternalInputs of the given net.
    """
    if isinstance(schema, Scalar):
        result = schema.clone()
        result.set_value(
            blob=ScopedBlobReference(net.NextName('unnamed_scalar')))
        return result

    assert isinstance(schema, Field), 'Record must be a schema.Field instance.'
    blob_refs = [
        net.AddExternalInput(net.NextName(prefix=name))
        for name in schema.field_names()]
    return from_blob_list(schema, blob_refs)


def ConstRecord(net, array_record):
    """
    Given a record of arrays, returns a record of blobs,
    initialized with net.Const.
    """
    blob_record = NewRecord(net, array_record)
    for blob, array in zip(
            blob_record.field_blobs(),
            array_record.field_blobs()):
        net.Const(array, blob)
    return blob_record


def InitEmptyRecord(net, schema_or_record):
    if not schema_or_record.has_blobs():
        record = NewRecord(net, schema_or_record)
    else:
        record = schema_or_record
    for blob in record.field_blobs():
        net.ConstantFill([], blob, shape=[0])
    return record


_DATA_TYPE_FOR_DTYPE = [
    (np.str, core.DataType.STRING),
    (np.float32, core.DataType.FLOAT),
    (np.float64, core.DataType.DOUBLE),
    (np.bool, core.DataType.BOOL),
    (np.int8, core.DataType.INT8),
    (np.int16, core.DataType.INT16),
    (np.int32, core.DataType.INT32),
    (np.int64, core.DataType.INT64),
    (np.uint8, core.DataType.UINT8),
    (np.uint16, core.DataType.UINT16),
]


def is_schema_subset(schema, original_schema):
    # TODO add more checks
    return set(schema.field_names()).issubset(
        set(original_schema.field_names()))


def equal_schemas(schema, original_schema):
    assert isinstance(schema, Field)
    assert isinstance(original_schema, Field)
    # TODO allow for more compatibility
    return schema.field_names() == original_schema.field_names() and\
        schema.field_types() == original_schema.field_types()


def schema_check(schema, previous=None):
    record = as_record(schema)
    if previous is not None:
        assert equal_schemas(schema, previous)
    return record


def data_type_for_dtype(dtype):
    for np_type, dt in _DATA_TYPE_FOR_DTYPE:
        if dtype.base == np_type:
            return dt
    raise TypeError('Unknown dtype: ' + str(dtype.base))


def attach_metadata_to_scalars(field, metadata):
    for f in field.all_scalars():
        f.set_metadata(metadata)
