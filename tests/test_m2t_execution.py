"""M2T context and chain acceptance; requires the real Mako dependency."""
from pathlib import Path
from unittest import mock
import pytest
from pyecore import ecore as E
from pyecore.resources import ResourceSet, URI
from motra import m2m, m2t
from motra.chain import ChainEngine
from motra.chainengine import Interactive


def renderer():
    t = m2t.Transformation('text')
    @t.main
    def main(self:E.EClass):
        """${label(self)}"""
    @t.template
    def label(self:E.EClass):
        """${prefix}${self.name}"""
    return t, label


def test_repeated_render_uses_current_model_and_parameters():
    t, label = renderer()
    node = E.EClass('A')
    assert 'one:A' in t.run(node, prefix='one:')
    node.name = 'B'
    assert 'two:B' in t.run(node, prefix='two:')
    with pytest.raises(RuntimeError):
        label(node)


def test_failure_restores_m2t_global():
    t, label = renderer()
    sentinel = object()
    with mock.patch.object(m2t, 'mycontext', sentinel, create=True):
        with pytest.raises(Exception):
            t.run(E.EClass('A'))  # prefix missing in real Mako context
        assert m2t.mycontext is sentinel
        assert 'ok:A' in t.run(E.EClass('A'), prefix='ok:')


def test_nested_render_restores_outer_context():
    outer, label = renderer()
    inner, other_label = renderer()
    @outer.helper
    def nested():
        return inner.run(E.EClass('inside'), prefix='nested:')
    @outer.main
    def extra(self:E.EClass):
        """${nested()} ${label(self)}"""
    text = outer.run(E.EClass('outside'), prefix='outer:')
    assert 'nested:inside' in text
    assert text.count('outer:outside') == 2


def test_forward_m2t_annotations():
    t = m2t.Transformation('forward')
    namespace={'t':t}
    exec("@t.main\ndef main(self: 'LateClass'):\n    '''${self.name}'''\n",namespace)
    package=E.EPackage('late',nsURI='urn:late',nsPrefix='late')
    node=E.EClass('LateClass')
    node.eStructuralFeatures.append(E.EAttribute('name',E.EString))
    package.eClassifiers.append(node)
    t.metamodels.add(package)
    assert 'late' in t.run(node(name='late'))


class Reload(Interactive):
    def __init__(self,path):
        super().__init__()
        self.path=path
    def execute(self,resource):
        return self.chain.resource_set.get_resource(URI(str(self.path)))


def test_chain_m2m_save_reload_m2t(tmp_path,capsys):
    copy=m2m.Transformation('copy',['source'],['target'])
    @copy.mapping
    def rule(self:E.EPackage)->E.EPackage:
        result.name=self.name
    @copy.main
    def main(source,target):
        rule(source.contents[0])
    text=m2t.Transformation('text')
    @text.main
    def render(self:E.EPackage):
        """<%motra:file path="${output_path}" append="${False}">${self.name}</%motra:file>${self.name}"""
    path=tmp_path/'saved.ecore'
    output=tmp_path/'output.txt'
    # Chain passes resources to M2T. Use a helper for output path rather than
    # adding a new ChainEngine.run keyword argument.
    @text.helper
    def output_file():
        return str(output)
    text.full_template=text.full_template.replace('${output_path}','${output_file()}')
    engine=ChainEngine('accept').m2m(copy).save(str(path)).interaction(Reload(path)).m2t(text)
    for name in ('Élément','Second'):
        resource=engine.run(E.EPackage(name))
        assert resource.contents[0].name==name
        assert output.read_text(encoding='utf-8').strip()==name
        assert name in capsys.readouterr().out
        assert not hasattr(engine.chain,'resource_set')


def test_template_buffer_restored_after_caught_exception():
    t=m2t.Transformation('buffer')
    @t.template
    def broken(self:E.EClass):
        """${1 / 0}"""
    @t.template
    def good(self:E.EClass):
        """${self.name}"""
    @t.helper
    def recover(node):
        try:
            broken(node)
        except ZeroDivisionError:
            pass
        return good(node)
    @t.main
    def main(self:E.EClass):
        """before:${recover(self)}:after"""
    assert 'before:A:after' in t.run(E.EClass('A'))


def test_decorators_still_available_after_render():
    t,label=renderer()
    t.run(E.EClass('A'),prefix='a:')
    @t.template
    def later(self:E.EClass):
        """${self.name}"""
    assert callable(later)


def test_polymorphic_templates_preserve_order_and_guards():
    t=m2t.Transformation('polymorphic')
    @t.main
    def main(self:E.EPackage):
        """${describe(self)}"""
    @t.main
    def child(self:E.EClass):
        """${describe(self)}"""
    @t.template(when=lambda self:self.name.startswith('Special'))
    def describe(self:E.EClass):
        """special:${self.name}"""
    @t.template
    def describe(self:E.EClass):
        """class:${self.name}"""
    @t.template
    def describe(self:E.EPackage):
        """package:${self.name}"""
    package=E.EPackage('root')
    package.eClassifiers.extend([E.EClass('SpecialA'),E.EClass('B')])
    text=t.run(package)
    assert 'package:root' in text
    assert 'special:SpecialA' in text
    assert 'class:B' in text


def test_chain_m2t_exception_restores_chain_and_render_context():
    t=m2t.Transformation('failure')
    @t.main
    def main(self:E.EPackage):
        """${1 / 0}"""
    engine=ChainEngine('failure').m2t(t)
    with pytest.raises(ZeroDivisionError):
        engine.run(E.EPackage('root'))
    assert not hasattr(engine.chain,'resource_set')
    assert m2t._context.get() is None


def test_nested_template_inside_file_tag(tmp_path):
    t,label=renderer()
    path=tmp_path/'nested.txt'
    @t.main
    def write(self:E.EClass):
        """<%motra:file path="${path}">${label(self)}</%motra:file>"""
    t.run(E.EClass('A'),prefix='nested:',path=str(path))
    assert path.read_text(encoding='utf-8').strip()=='nested:A'
