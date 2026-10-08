from pathlib import Path
import pytest
from pyecore import ecore as E
from motra.chain import ChainEngine
from motra.chainengine import Interactive
from motra import m2m


class Fail(Interactive):
    def execute(self, resource):
        raise ValueError('step failed')


def test_chain_restores_resource_set_on_failure():
    engine = ChainEngine('failure').interaction(Fail())
    sentinel = object()
    engine.chain.resource_set = sentinel
    with pytest.raises(ValueError, match='step failed'):
        engine.run(E.EClass('A'))
    assert engine.chain.resource_set is sentinel


def test_chain_does_not_mask_transformation_attribute_error():
    t = m2m.Transformation('error', ['source'], ['target'])
    @t.main
    def main(source, target):
        raise AttributeError('body failure')
    with pytest.raises(AttributeError, match='body failure'):
        ChainEngine('failure').m2m(t).run(E.EClass('A'))


def test_chain_repeated_save(tmp_path):
    t = m2m.Transformation('copy', ['source'], ['target'])
    @t.mapping
    def copy(self:E.EClass) -> E.EClass:
        result.name = self.name
    @t.main
    def main(source,target):
        copy(source.contents[0])
    target=tmp_path/'saved.ecore'
    engine=ChainEngine('repeat').m2m(t).save(str(target))
    for name in ('A','B'):
        resource=engine.run(E.EClass(name))
        assert resource.contents[0].name==name
        assert target.is_file()
        assert not hasattr(engine.chain,'resource_set')
