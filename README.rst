=========================================
Motra: Models Transformations for PyEcore
=========================================

Motra is a librairie providing model transformations facilities to PyEcore.
The goal of the librairie is to propose a set of embedded DSLs in Python for models to models transformations (M2M) and model to text transformations (M2T) with advanced traceability mechanism.
Here are some characteristics about Motra M2M:

* it proposes a semantic close to QVTo, imperative, based on ``mappings`` where the execution order is defined by the developer in each mapping,
* it supports multiple input and multiple outputs,
* each ``mapping`` result is cached and when a mapping is called twice with a same set of parameters, the exact same created object is returned,
* by default, any object created in a ``mapping`` that is not explicitaly placed in a container is automatically added as model root,
* used metamodels are automatically registered for smooth load/save of any models.
* it supports ``mapping`` polymorphism without having to rely on manual coding a dispatch with a ``disjunct`` (if the mappings own the same name)


Documentation
=============

Documentation is still a WIP and can be found here: https://motra.readthedocs.io/.
For more examples, please refer to transformations examples in ``examples``.
To avoid the need to load/install special metamodels, all the transformations examples are given directly over Ecore.
The transformations are gathered in simple modules depending to their characteristics: in-place, in-out, endogenous or exogenous.


M2M Quick start
===============

Each transformation must be defined in it's own Python module (even if multiple transformations can be defined in one module).

.. code-block:: python

    # import the input and output metamodels
    import ghmde  # based on https://github.com/kolovos/datasets/blob/master/github-mde/ghmde.ecore
    import graph  # based on a simple graph metamodel

    # import motra for utils and for M2M transformation definition
    import motra
    from motra import m2m

    # M2M transformation "signature" definition
    ghmde2graph = m2m.Transformation('ghmde2graph',
                                     inputs=['ghmde_model'],
                                     outputs=['graph_model'])


    # defines the entry point of the transformation
    @ghmde2graph.main
    def main(ghmde_model, graph_model):
        print('Transforming repository to graph', graph_model)
        for f in motra.objects_of_kind(ghmde_model, ghmde.File):
            file2node(f)
        for repository in motra.objects_of_kind(ghmde_model, ghmde.Repository):
            repository2graph(repository, postfix='_graph')
        # m2m.objects_of_kind

    # defines a first mapping transforming Files in Node
    @ghmde2graph.mapping
    def file2node(self: ghmde.File) -> Node:
        result.name = self.path   # The "result" variable is automatically created and injected in the current context


    # defines a conditional mapping from Repository to Graph
    def does_not_starts_with(self, postfix):
        return not self.name.startswith(postfix)

    @ghmde2graph.mapping(when=does_not_starts_with)
    def repository2graph(self: ghmde.Repository, postfix: str) -> Graph:
        result.name = self.name + postfix
        for repo_file in self.files:
            result.nodes.append(file2node(repo_file))


Then, it can be imported and directly used from another module.
Currently, there is no default runner, but there will be in the future, a way of defining models transformations chains.

.. code-block:: python

    # Import the transformation
    from transfo_example import ghmde2graph

    # Just run it. Input can be a "Resource" or directly a file
    result_context = ghmde2graph.run(ghmde_model="input_model.xmi")*

    # A result context gives access to:
    # * the inputs
    # * the outputs
    # * the execution trace (still WIP)
    # * the transformation definition
    # * the used resource set for this transformation
    result_context.inputs.ghmde_model.save(output="input_copy.xmi")
    result_context.outputs.graph_model.save(output="test.xmi")



M2T Quick start
===============

As for M2M, a M2T transformation must be defined in it's own Python module (even if multiple transformations can be defined in one module as defined in the module ``examples/m2t/sample.py``).
Each template code is written as ``__doc__`` of template functions.

.. code-block:: python

    from motra import m2t
    import pyecore.ecore as ecore

    # M2T transformation "signature" definition
    ecore2simplejava = m2t.Transformation("ecore2simplejava")

    # Definition of the main entry point.
    # At the moment, entry-point cannot have "when=" parameter
    # The special <%motra:file ><%/motra:file> is used to specify blocs
    # where the code must be written. Multiple "file" tags can be introduced by template.
    @ecore2simplejava.main
    def eclass2class(self: ecore.EClass):
        """
    <%motra:file path="examples/outputs/${self.ePackage.name}/${self.name}.java">
    public class ${self.name.capitalize()} {
        % for feature in self.eStructuralFeatures:
        // ${override(feature)}
        ${feature2attribute(feature)}
        % endfor
    }
    </%motra:file>
    """

    @ecore2simplejava.template(
        when=lambda self: self.many
    )
    def feature2attribute(self: ecore.EAttribute):
        """List<${self.eType.name}> ${self.name}; // many attribute"""


    @ecore2simplejava.template
    def feature2attribute(self: ecore.EAttribute):
        """${self.eType.name} ${self.name}; // single attribute"""


    @ecore2simplejava.template(
        when=lambda self: self.many
    )
    def feature2attribute(self: ecore.EReference):
        """List<${self.eType.name}> ${self.name}; // many reference"""


    @ecore2simplejava.template
    def feature2attribute(self: ecore.EReference):
        """List<${self.eType.name}> ${self.name}; // single reference"""


    @ecore2simplejava.template
    def override(self: ecore.EAttribute):
        """Attribut ${self.name}: ${self.eType.name} [${self.lowerBound}..${upper2symbol(self)}]"""


    @ecore2simplejava.template
    def override(self: ecore.EReference):
        """Reference ${self.name}: ${self.eType.name} [${self.lowerBound}..${upper2symbol(self)}]"""


    @ecore2simplejava.helper
    def upper2symbol(self: ecore.EStructuralFeature):
        return '*' if self.many else self.upperBound


Then, it can be imported and directly used from another module.
Currently, there is no default runner, but there will be in the future, a way of defining models transformations chains.

.. code-block:: python

    # Import the transformation
    from examples.m2t.sample import ecore2simplejava

    # Just run it. Input can be a "Resource", a model or directly a file
    ecore2simplejava.run('examples/inputs/input.ecore')


Execution identity and Python compatibility
------------------------------------------

Python 3.12 or newer is required. The mapping cache belongs to one execution:
source EObject identity, mapping and bound parameters identify a result. Positional
and equivalent keyword calls share that result. There is no eviction while running;
cyclic mappings see a reserved result before its body traverses other objects.
Memory grows with the number of distinct mapping calls in that execution.

By default caches are cleared on success and failure. With
``clean_mappings_cache=False``, a successful execution retains its cache for inspection
until ``context.clear_cache()`` or release of that execution context. A new run always
has a fresh cache, even with that flag. Cross-run result reuse is intentionally removed:
results belong to the output resources of their own execution. Mapping calls outside
an active matching transformation raise RuntimeError, including previous cache hits.
``cache_info`` and ``cache_clear`` remain available on decorated mappings. Sources
and other parameters must remain hashable as required by the previous cache API.

Use ``motra.m2m.current_execution()`` and ``current_result()`` in new mapping bodies.
Existing bodies using the injected global ``result`` remain compatible; its old value
is restored on success, exceptions and nested calls. ContextVar isolates execution
selection but does not eliminate that compatibility injection. No thread safety,
async mapping or Python without GIL guarantee is made.

An exception clears caches and newly created output resources; mutations to input
or inout models, external resources and files are not rolled back. Reentrant runs
restore the outer execution context and do not clear its cache. Chain resource sets
are similarly restored on errors, and errors in transformation bodies propagate
without being relabelled as missing chain contexts.

Annotations may refer to names defined later. Available types are remembered at
decoration time; forward names are resolved at execution time, after metamodels
have been registered in ``transformation.metamodels``; ordinary
function globals and classifier/package names in those metamodels are available.
Unresolved or invalid annotations raise errors rather than silently changing dispatch.
Annotations are trusted Python code, not a security boundary.

M2T creates a new rendering context for every run. Rendered text is not memoized,
since it depends on mutable models, template parameters and helper side effects.
Nested runs and caught template errors restore the outer rendering buffers. Existing
polymorphic registration order and guards remain supported. Files are UTF-8; the
historical file tag replaces its destination even for ``append=True``. Multiple
file writes are not a transaction.

Building and testing
--------------------

Build metadata declares a static version without importing the runtime, and includes
trace, chainengine and the Ecore metamodel in sdist/wheel. Existing generated chainengine
sources are shipped; builds do not regenerate them or download a generation plugin.
For intentional regeneration, review the generated diff separately::

    python -m pyecoregen.cli -e motra/metamodels/chainengine.ecore -o motra --user-module motra.chainengine.chainengine_mixins

Do not regenerate trace or examples as part of a normal build. Then::

    python -m build
    python -m pytest tests

The migration harness installs explicit local ecosystem forks and uses a prepared
offline wheelhouse. Mako must be prepared there as a real dependency; it is not
replaced by a stub or silently ignored. HOT remains an unmerged research branch.
