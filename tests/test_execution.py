"""Execution identity, context restoration and annotation contracts."""
import gc
import weakref
from unittest import mock
import pytest
from pyecore import ecore as E
from motra import m2m


def make_transformation():
    t = m2m.Transformation('copy', ['source'], ['target'])
    @t.mapping
    def copy(self: E.EClass) -> E.EClass:
        result.name = self.name
    @t.main
    def main(source, target):
        copy(source.contents[0])
    return t, copy


def test_failure_restores_globals_and_does_not_publish_partial_result():
    t, copy = make_transformation()
    sentinel = object()
    source = E.EClass('A')
    with mock.patch.object(m2m, 'mycontext', sentinel, create=True):
        @t.mapping
        def fail(self: E.EClass) -> E.EClass:
            result.name = 'partial'
            raise RuntimeError('broken')
        @t.main
        def main(source, target):
            fail(source.contents[0])
        from pyecore.resources import ResourceSet
        rs = ResourceSet()
        with pytest.raises(RuntimeError, match='broken'):
            t.run(source=source, resource_set=rs)
        assert m2m.mycontext is sentinel
        assert all(not r.contents for r in rs.resources.values() if r.uri.plain == 'target')
        assert 'result' not in globals()
        with pytest.raises(RuntimeError):
            copy(source)


def test_more_than_128_objects_keep_identity(request):
    t, copy = make_transformation()
    sources = [E.EClass(str(n)) for n in range(300)]
    @t.main
    def main(source, target):
        first = copy(sources[0])
        for obj in sources[1:]:
            copy(obj)
        assert copy(sources[0]) is first
    context = t.run(source=E.EPackage())
    assert len(context.outputs.target.contents) == 300


def test_nested_execution_of_same_transformation():
    t, copy = make_transformation()
    observed = []
    @t.main
    def main(source, target, nested=False):
        first = copy(source.contents[0])
        if not nested:
            inner = t.run(source=E.EClass('nested'), nested=True)
            observed.append(inner.outputs.target.contents[0])
        assert copy(source.contents[0]) is first
    context = t.run(source=E.EClass('outer'))
    assert context.outputs.target.contents[0].name == 'outer'
    assert observed[0].name == 'nested'
    assert observed[0] is not context.outputs.target.contents[0]


def test_cycles_publish_result_before_body():
    t = m2m.Transformation('cycle', ['source'], ['target'])
    Node = E.EClass('Node')
    Node.eStructuralFeatures.append(E.EAttribute('name', E.EString))
    Node.eStructuralFeatures.append(E.EReference('next', Node))
    @t.mapping
    def copy(self: Node) -> Node:
        result.name = self.name
        if self.next is not None:
            result.next = copy(self.next)
    @t.main
    def main(source, target):
        copy(source.contents[0])
    a, b = Node(name='A'), Node(name='B')
    a.next = b
    b.next = a
    context = t.run(source=a)
    out = context.outputs.target.contents
    assert len(out) == 2
    first = next(x for x in out if x.name == 'A')
    assert first.next.next is first


def test_retained_cache_is_execution_scoped_and_released():
    t, copy = make_transformation()
    source = E.EClass('A')
    first = t.run(source=source, clean_mappings_cache=False)
    result1 = first.outputs.target.contents[0]
    second = t.run(source=source, clean_mappings_cache=False)
    assert second.outputs.target.contents[0] is not result1
    assert copy.cache_info().currsize == 1
    reference = weakref.ref(second)
    del second
    gc.collect()
    assert reference() is None
    assert copy.cache_info().currsize == 0
    with pytest.raises(RuntimeError):
        copy(source)


def test_forward_annotations_resolved_after_registration():
    t = m2m.Transformation('forward', ['source'], ['target'])
    namespace = {'t': t}
    exec("@t.mapping\ndef copy(self: 'LateNode') -> 'LateNode':\n    result.name = self.name\n", namespace)
    package = E.EPackage('late', nsURI='urn:late', nsPrefix='late')
    node = E.EClass('LateNode')
    package.eClassifiers.append(node)
    t.metamodels.add(package)
    @t.main
    def main(source, target):
        namespace['copy'](source.contents[0])
    context = t.run(source=node(name='late'))
    assert context.outputs.target.contents[0].name == 'late'


def test_outputs_follow_declared_order():
    t = m2m.Transformation('outputs', ['source'], ['zeta', 'alpha', 'beta'])
    @t.main
    def main(**kwargs):
        pass
    context = t.run(source=E.EClass('A'))
    assert [r.uri.plain for r in context.resource_set.resources.values()][-3:] == ['zeta', 'alpha', 'beta']


def test_explicit_context_api_and_legacy_result_restoration():
    t = m2m.Transformation('explicit', ['source'], ['target'])
    child, child_copy = make_transformation()
    marker = object()
    with mock.patch.dict(globals(), {'result': marker}):
        @t.mapping
        def parent(self:E.EClass) -> E.EClass:
            active = m2m.current_execution()
            out = m2m.current_result()
            assert out is result
            child.run(source=E.EClass('child'))
            assert m2m.current_execution() is active
            assert m2m.current_result() is out
            assert result is out
            out.name = self.name
        @t.main
        def main(source,target):
            parent(source.contents[0])
        context=t.run(source=E.EClass('parent'))
        assert result is marker
        assert context.outputs.target.contents[0].name=='parent'
        assert parent.cache_info().currsize==0
    with pytest.raises(RuntimeError):
        m2m.current_execution()


def test_native_or_future_deferred_annotations():
    import sys
    t=m2m.Transformation('deferred',['source'],['target'])
    namespace={'t':t}
    prefix='from __future__ import annotations\n' if sys.version_info < (3,14) else ''
    exec(prefix + '@t.mapping\ndef copy(self: Later) -> Later:\n    result.name=self.name\n',namespace)
    namespace['Later']=E.EPackage
    @t.main
    def main(source,target):
        namespace['copy'](source.contents[0])
    assert t.run(source=E.EPackage('deferred')).outputs.target.contents[0].name=='deferred'


def test_failed_retained_cache_is_cleared():
    t,copy=make_transformation()
    @t.main
    def main(source,target):
        copy(source.contents[0])
        assert copy.cache_info().currsize==1
        raise RuntimeError('stop')
    with pytest.raises(RuntimeError,match='stop'):
        t.run(source=E.EClass('A'),clean_mappings_cache=False)
    assert copy.cache_info().currsize==0


def test_keyword_and_positional_calls_share_source_identity():
    t,copy=make_transformation()
    @t.main
    def main(source,target):
        obj=source.contents[0]
        assert copy(obj) is copy(self=obj)
    assert len(t.run(source=E.EClass('A')).outputs.target.contents)==1



def test_scalar_mapping_result_has_no_resource_attachment():
    t=m2m.Transformation('scalar',['source'],['target'])
    values=[]
    @t.mapping
    def scalar(self:E.EClass) -> str:
        pass
    @t.main
    def main(source,target):
        values.append(scalar(source.contents[0]))
    context=t.run(source=E.EClass('A'))
    assert values==['']
    assert len(context.outputs.target.contents)==0
