import typing
import contextvars
import weakref
from collections import namedtuple
import functools
import inspect
import pyecore.ecore as Ecore
from pyecore.resources import ResourceSet, URI, Resource
from pyecore.notification import EObserver
from . import trace


class ResultObserver(EObserver):
    def notifyChanged(self, notif):
        print(notif)


class EObjectProxy(object):
    def __init__(self, instance):
        object.__setattr__(self, 'wrapped', instance)
        object.__setattr__(self, 'wrapped_eClass', instance.eClass)

    def __getattribute__(self, name):
        wrapped = object.__getattribute__(self, 'wrapped')
        eClass = object.__getattribute__(self, 'wrapped_eClass')
        result = getattr(wrapped, name)
        # if eClass.findEStructuralFeature(name):
        #     print('access', name, ':', result, 'for', wrapped)
        return result

    def __eq__(self, other):
        return object.__getattribute__(self, 'wrapped').__eq__(other)

    def __hash__(self):
        return object.__getattribute__(self, 'wrapped').__hash__()

    def __setattr__(self, name, value):
        wrapped = object.__getattribute__(self, 'wrapped')
        if isinstance(value, EObjectProxy):
            value = object.__getattribute__(value, 'wrapped')
        return setattr(wrapped, name, value)

    def __str__(self):
        wrapped = object.__getattribute__(self, 'wrapped')
        return wrapped.__str__()


class Parameters(object):
    def __init__(self, transformation, parameter_names):
        self.transformation = transformation
        self.parameter_names = parameter_names

    def __getitem__(self, item):
        if type(item) is str:
            return getattr(self, item)
        return getattr(self, self.parameter_names[item])

    def __len__(self):
        return len(self.parameter_names)


_execution = contextvars.ContextVar('motra_m2m_execution', default=None)
_result = contextvars.ContextVar('motra_m2m_result', default=None)
_CacheInfo = namedtuple('CacheInfo', 'hits misses maxsize currsize')


def current_execution():
    context = _execution.get()
    if context is None:
        raise RuntimeError('Mapping cannot be executed outside of the transformation.')
    return context


def current_result():
    current_execution()
    return _result.get()


def _signature(f):
    # Python 3.14 must not force deferred annotations at decoration time.
    try:
        from annotationlib import Format
    except ImportError:
        return inspect.signature(f, eval_str=False)
    return inspect.signature(f, annotation_format=Format.STRING)


def _unwrap(value):
    if isinstance(value, EObjectProxy):
        return object.__getattribute__(value, 'wrapped')
    return value


class _Identity:
    def __init__(self, value):
        self.value = value

    def __hash__(self):
        return id(self.value)

    def __eq__(self, other):
        return isinstance(other, _Identity) and self.value is other.value


def _key_value(value):
    value = _unwrap(value)
    return _Identity(value) if isinstance(value, Ecore.EObject) else value


class Transformation(object):
    def __init__(self, name, inputs, outputs):
        self.name = name
        self.inputs_def = inputs
        self.outputs_def = outputs
        self.metamodels = set()
        self.registered_mappings = []
        self._main = None
        self._polymorphic_calls = {}

    @property
    def inouts(self):
        return [k for k in self.inputs_def if k in self.outputs_def]

    def main(self, fun):
        self._main = fun
        fun.__transformation__ = self
        return fun

    def run(self, clean_mappings_cache=True, resource_set=None, **kwargs):
        if self._main is None:
            raise RuntimeError("Your transformation doesn't have a main entry point")
        # Resolve only after the caller has registered its metamodels.
        for mapping in self.registered_mappings:
            if getattr(mapping, '__mapping__', False):
                self._resolve_mapping(mapping)
        context = TransformationExecution(self, resource_set)
        rset = context.resource_set
        for mm in self.metamodels:
            rset.metamodel_registry[mm.nsURI] = mm
        token = _execution.set(context)
        created_outputs = []
        succeeded = False
        try:
            params = {}
            for in_model in self.inputs_def:
                if in_model not in kwargs:
                    raise KeyError(f'{in_model} is a missing input model')
                param = kwargs.pop(in_model)
                if isinstance(param, Ecore.EObject):
                    resource = param.eResource
                    if resource is None:
                        resource = rset.create_resource(URI(in_model))
                        resource.append(param)
                elif isinstance(param, Resource):
                    resource = param
                else:
                    resource = rset.get_resource(param)
                setattr(context.inputs, in_model, resource)
                params[in_model] = resource
                if in_model in self.inouts:
                    setattr(context.outputs, in_model, resource)
            for out_model in self.outputs_def:
                if out_model in self.inouts:
                    continue
                resource = rset.create_resource(URI(out_model))
                setattr(context.outputs, out_model, resource)
                params[out_model] = resource
                created_outputs.append(resource)
            context.primary_output = context.outputs[0] if self.outputs_def else None
            params.update(kwargs)
            self._main(**params)
            succeeded = True
            return context
        finally:
            _execution.reset(token)
            if not succeeded:
                for resource in created_outputs:
                    resource.contents.clear()
            if clean_mappings_cache or not succeeded:
                context.clear_cache()

    def _remember_package(self, eclass):
        if eclass is None:
            return
        if hasattr(eclass, '_staticEClass'):
            package = eclass.eClass.ePackage
        elif isinstance(eclass, Ecore.EObject):
            package = eclass.ePackage
        else:
            return
        if package is not None:
            self.metamodels.add(package)

    def _resolve_mapping(self, f):
        from pyecore.utils import DynamicEPackage
        namespace = {}
        for package in self.metamodels:
            namespace[package.name] = DynamicEPackage(package)
            for classifier in package.eClassifiers:
                namespace[classifier.name] = getattr(classifier, 'python_class', classifier)
        hints = typing.get_type_hints(f, localns=namespace)
        f.self_eclass = hints.get('self')
        f.result_eclass = hints.get('return')
        if f.self_eclass is None:
            raise ValueError(f"Missing 'self' parameter for mapping: '{f.__name__}'")
        f.inout = f.result_eclass is None
        f.output_def = None if f.inout else f._output_model
        self._remember_package(f.self_eclass)
        self._remember_package(f.result_eclass)
        if hasattr(f, 'cache'):
            f.cache.self_eclass = f.self_eclass
            f.cache.result_eclass = f.result_eclass
            f.cache.inout = f.inout
            f.cache.output_def = f.output_def

    def _memoized(self, f, operation):
        signature = _signature(f)
        last_context = None

        @functools.wraps(f)
        def cached(*args, **kwargs):
            nonlocal last_context
            context = current_execution()
            if context.transformation is not self:
                raise RuntimeError('Mapping belongs to another transformation')
            last_context = weakref.ref(context)
            arguments = signature.bind(*args, **kwargs)
            arguments.apply_defaults()
            parts = []
            for name, value in arguments.arguments.items():
                kind = signature.parameters[name].kind
                if kind is inspect.Parameter.VAR_KEYWORD:
                    value = tuple(sorted((k, _key_value(v)) for k, v in value.items()))
                elif kind is inspect.Parameter.VAR_POSITIONAL:
                    value = tuple(_key_value(v) for v in value)
                else:
                    value = _key_value(value)
                parts.append((name, value))
            key = tuple(parts)
            cache = context.caches.setdefault(cached, {})
            stats = context.cache_stats.setdefault(cached, [0, 0])
            if key in cache:
                stats[0] += 1
                return cache[key]
            stats[1] += 1
            try:
                value = operation(cache, key, *args, **kwargs)
                cache[key] = value
                return value
            except BaseException:
                cache.pop(key, None)
                raise

        def cache_context():
            context = _execution.get()
            if context is not None and context.transformation is self:
                return context
            return last_context() if last_context is not None else None

        def cache_clear():
            context = cache_context()
            if context is not None:
                context.caches.pop(cached, None)
                context.cache_stats.pop(cached, None)

        def cache_info():
            context = cache_context()
            stats = context.cache_stats.get(cached, [0, 0]) if context else [0, 0]
            size = len(context.caches.get(cached, {})) if context else 0
            return _CacheInfo(*stats, None, size)

        cached.cache_clear = cache_clear
        cached.cache_info = cache_info
        cached.cache_parameters = lambda: {'maxsize': None, 'typed': False}
        f.cache = cached
        return cached

    def mapping(self, f=None, output_model=None, when=None):
        if f is None:
            return functools.partial(self.mapping, output_model=output_model, when=when)
        parameter = _signature(f).parameters.get('self')
        if parameter is None or parameter.annotation is inspect.Parameter.empty:
            raise ValueError(f"Missing 'self' parameter for mapping: '{f.__name__}'")
        f.__mapping__ = True
        f.__transformation__ = self
        f.self_eclass = f.result_eclass = None
        f.inout = False
        f.when = when
        f._output_model = output_model or (self.outputs_def[0] if self.outputs_def else None)
        f.output_def = f._output_model
        try:
            self._resolve_mapping(f)
        except NameError:
            # Forward names may only become available after metamodel registration.
            pass
        self._polymorphic_calls.setdefault(f.__name__, []).append(f)
        self.registered_mappings.append(f)

        def inner(cache, key, *args, **kwargs):
            self_parameter = _unwrap(_signature(f).bind(*args, **kwargs).arguments['self'])
            for candidate in self._polymorphic_calls[f.__name__]:
                if isinstance(self_parameter, candidate.self_eclass):
                    if candidate.when is None or candidate.when(*args, **kwargs):
                        func = candidate
                        break
            else:
                return None
            if func.inout:
                result = self_parameter
            elif func.result_eclass is Ecore.EClass:
                result = func.result_eclass('')
            else:
                result = func.result_eclass()
            # Reserve the identity before traversing cycles.
            cache[key] = result
            context = current_execution()
            result_token = _result.set(result)
            g = func.__globals__
            marker = object()
            oldvalue = g.get('result', marker)
            g['result'] = result  # compatibility for existing mapping bodies
            new_args = [EObjectProxy(_unwrap(obj)) if isinstance(_unwrap(obj), Ecore.EObject)
                        else obj for obj in args]
            new_kwargs = {k: EObjectProxy(_unwrap(v)) if isinstance(_unwrap(v), Ecore.EObject)
                          else v for k, v in kwargs.items()}
            try:
                func(*new_args, **new_kwargs)
            finally:
                _result.reset(result_token)
                if oldvalue is marker:
                    g.pop('result', None)
                else:
                    g['result'] = oldvalue
            # Failed mapping results are never attached to outputs.
            if not func.inout and func.output_def and getattr(result, 'eResource', False) is None:
                context.outputs[func.output_def].append(result)
            return result
        return self._memoized(f, inner)

    def disjunct(self, f=None, mappings=None):
        if f is None:
            return functools.partial(self.disjunct, mappings=mappings)
        self.registered_mappings.append(f)
        def inner(cache, key, *args, **kwargs):
            result = None
            for fun in mappings:
                result = fun(*args, **kwargs)
                if result is not None:
                    break
            f(*args, **kwargs)
            return result
        return self._memoized(f, inner)


class TransformationExecution(object):
    def __init__(self, transfo, resource_set=None):
        self.trace = trace.TransformationTrace()
        self.inputs = Parameters(transfo, transfo.inputs_def)
        self.outputs = Parameters(transfo, transfo.outputs_def)
        self.transformation = transfo
        self.resource_set = resource_set if resource_set is not None else ResourceSet()
        self.caches = {}
        self.cache_stats = {}

    def clear_cache(self):
        self.caches.clear()
        self.cache_stats.clear()
