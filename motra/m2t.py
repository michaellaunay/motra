import contextvars
import functools
import inspect
import typing
from io import StringIO
from pathlib import Path
import pyecore.ecore as Ecore
from pyecore.utils import DynamicEPackage
from pyecore.resources import ResourceSet, Resource, URI
from mako.template import Template
from mako.runtime import Context, Undefined
from .m2m import _signature


_context = contextvars.ContextVar('motra_m2t_context', default=None)


def in_file(path, append, body):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the historical file tag replacement behavior (including append=True).
    mode = 'w+' if append else 'w'
    with open(path, mode, encoding='utf-8') as f:
        f.write(body)
    return ''


file_tag = """
<%namespace name="motra">
<%def name="file(path, append=True)"><%  body = capture(caller.body) %> ${in_file(path, append, body)}</%def>
</%namespace>
"""


class Transformation(object):
    def __init__(self, name):
        self.name = name
        self.mains = []
        self.file_tag = file_tag
        self.full_template = self.file_tag
        self.metamodels = set()
        self._polymorphic_calls = {}
        self.helpers = []

    def _remember_type(self, annotation):
        if hasattr(annotation, '_staticEClass'):
            package = annotation.eClass.ePackage
        elif isinstance(annotation, Ecore.EClass):
            package = annotation.ePackage
        else:
            return
        if package is not None:
            self.metamodels.add(package)

    def _resolve_type(self, f):
        namespace = {}
        for package in self.metamodels:
            namespace[package.name] = DynamicEPackage(package)
            for classifier in package.eClassifiers:
                namespace[classifier.name] = getattr(classifier, 'python_class', classifier)
        parameter = next(iter(_signature(f).parameters.values()))
        annotation = typing.get_type_hints(f, localns=namespace).get(parameter.name)
        if annotation is None:
            raise ValueError(f'Missing source annotation for template {f.__name__!r}')
        self._remember_type(annotation)
        f.source_type = annotation
        return annotation

    def run(self, model, resource_set=None, **kwargs):
        for (f, pname, etype), wrapper in self.mains:
            self._resolve_type(f)
        for wrappers in self._polymorphic_calls.values():
            for wrapper in wrappers:
                self._resolve_type(wrapper.__wrapped__)
        if isinstance(model, Resource):
            model = model.contents[0]
        elif isinstance(model, (str, URI)):
            rset = resource_set if resource_set is not None else ResourceSet()
            for metamodel in self.metamodels:
                rset.metamodel_registry[metamodel.nsURI] = metamodel
            model = rset.get_resource(model).contents[0]
        buf = StringIO()
        myprops = {'in_file': in_file}
        myprops.update(kwargs)
        for f in self.helpers:
            myprops[f.__name__] = f
        for name, templates in self._polymorphic_calls.items():
            myprops[name] = templates[0]
        for metamodel in self.metamodels:
            myprops[metamodel.name] = DynamicEPackage(metamodel)
        ctx = Context(buf, **myprops)
        token = _context.set((self, ctx))
        try:
            template = Template(self.full_template)
            for element in (model, *model.eAllContents()):
                for (fun, pname, etype), wrapper in self.mains:
                    if isinstance(element, fun.source_type):
                        template.get_def(fun.__name__).render_context(ctx, element)
            return buf.getvalue()
        finally:
            _context.reset(token)
            buf.close()

    def _register_template(self, f):
        self.full_template += '\n<%def name="{}({})">{}</%def>\n'.format(
            f.__name__, ', '.join(_signature(f).parameters), f.__doc__)

    def main(self, f):
        if not f.__doc__:
            return f
        parameter = next(iter(_signature(f).parameters.values()))
        try:
            self._resolve_type(f)
        except NameError:
            pass
        self.mains.append(((f, parameter.name, None), f))
        self._register_template(f)
        return f

    def template(self, f=None, when=None):
        if f is None:
            return functools.partial(self.template, when=when)
        f.when = when
        @functools.wraps(f)
        def inner(*args, **kwargs):
            active = _context.get()
            if active is None or active[0] is not self:
                raise RuntimeError('Template cannot be executed outside of the transformation.')
            ctx = active[1]
            parameter = next(iter(_signature(f).parameters))
            self_parameter = _signature(f).bind(*args, **kwargs).arguments[parameter]
            for wrapper in self._polymorphic_calls[f.__name__]:
                candidate = wrapper.__wrapped__
                if isinstance(self_parameter, candidate.source_type):
                    if candidate.when is None or candidate.when(*args, **kwargs):
                        func = candidate
                        break
            else:
                return Undefined
            old_io = ctx._buffer_stack[0]
            buf = StringIO()
            ctx._buffer_stack[0] = buf
            try:
                func.template.get_def(func.__name__).render_context(ctx, *args, **kwargs)
                return buf.getvalue()
            finally:
                ctx._buffer_stack[0] = old_io
                buf.close()
        self._polymorphic_calls.setdefault(f.__name__, []).append(inner)
        if f.__doc__:
            definition = '<%def name="{}({})">{}</%def>'.format(
                f.__name__, ', '.join(_signature(f).parameters), f.__doc__)
            f.template = Template(definition)
            try:
                self._resolve_type(f)
            except NameError:
                pass
        return inner

    def helper(self, f):
        self.helpers.append(f)
        return f
