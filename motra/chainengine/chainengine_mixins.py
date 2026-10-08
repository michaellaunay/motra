from pyecore.resources import ResourceSet, Resource, URI
from pyecore.ecore import EObject
"""Mixins to be implemented by user."""


class ChainMixin:
    """User defined mixin class for Chain."""

    def __init__(self, *, name=None, operations=None, **kwargs):
        super().__init__()

    def run(self, input=None):
        parameter = input
        marker = object()
        previous = getattr(self, 'resource_set', marker)
        self.resource_set = ResourceSet()
        try:
            for operation in self.operations:
                parameter = operation.execute(operation.prepare_execution(parameter))
            return parameter
        finally:
            if previous is marker:
                del self.resource_set
            else:
                self.resource_set = previous


class OperationMixin:
    """User defined mixin class for Operation."""

    def __init__(self, *, chain=None, **kwargs):
        super().__init__()

    def prepare_execution(self, param):
        if isinstance(param, Resource):
            return param
        rset = self.chain.resource_set
        if isinstance(param, (str, URI)):
            resource = rset.get_resource(param)
        if isinstance(param, EObject):
            if param.eResource:
                resource = param.eResource
            else:
                resource = rset.create_resource(f"tmp_{id(param)}")
                resource.append(param)
        if not isinstance(param, (Resource, str, URI, EObject)):
            raise TypeError('A chain step requires a resource, model or URI')
        return resource

    def execute(self, model=None):

        raise NotImplementedError('operation execute(...) not yet implemented')


class SerializationFormatMixin:
    """User defined mixin class for SerializationFormat."""

    def __init__(self, *, name=None, saves=None, **kwargs):
        super().__init__()


class TransformationMixin:
    """User defined mixin class for Transformation."""

    def __init__(self, *, implementation=None, **kwargs):
        super().__init__(**kwargs)


class InteractiveMixin:
    """User defined mixin class for Interactive."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class IOMixin:
    """User defined mixin class for IO."""

    def __init__(self, *, path=None, **kwargs):
        super().__init__(**kwargs)


class OperationExtensionMixin:
    """User defined mixin class for OperationExtension."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class SaveMixin:
    """User defined mixin class for Save."""

    def __init__(self, *, serializationformat=None, **kwargs):
        super().__init__(**kwargs)

    def execute(self, resource):
        resource.save(self.path)
        return resource


class M2MMixin:
    """User defined mixin class for M2M."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def execute(self, resource):
        inputdefs = self.implementation.inputs_def
        input_dict = {
            inputdefs[0]: resource
        }
        try:
            rset = self.chain.resource_set
        except AttributeError as e:
            raise RuntimeError("The transformation has to be launched from a chain") from e
        result = self.implementation.run(resource_set=rset, **input_dict)
        return result.outputs[0]


class M2TMixin:
    """User defined mixin class for M2T."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def execute(self, resource):
        try:
            rset = self.chain.resource_set
        except AttributeError as e:
            raise RuntimeError("The transformation has to be launched from a chain") from e
        result = self.implementation.run(resource, resource_set=rset)
        result = result.rstrip()
        if result:
            print(result)
        return resource


class LoadMixin:
    """User defined mixin class for Load."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
