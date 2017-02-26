#!/usr/bin/env python

import sys
import os
import subprocess as sp
from functools import partial
import shlex
import logging

import yaml
import argh
from argh import arg
import networkx as nx
from networkx.drawing.nx_pydot import write_dot
import pandas


from . import utils
from .build import build_recipes
from . import docker_utils
from . import lint_functions
from . import linting
from . import github_integration

logger = logging.getLogger(__name__)
# NOTE:
#
# A package is the name of the software package, like `bowtie`.
#
# A recipe is the path to the recipe of one version of a package, like
# `recipes/bowtie` or `recipes/bowtie/1.0.1`.


@arg('recipe_folder', help='Path to top-level dir of recipes.')
@arg('config', help='Path to yaml file specifying the configuration')
@arg(
    '--packages',
    nargs="+",
    help='Glob for package[s] to build. Default is to build all packages. Can '
    'be specified more than once')
@arg('--cache', help='''To speed up debugging, use repodata cached locally in
     the provided filename. If the file does not exist, it will be created the
     first time.''')
@arg('--list-funcs', help='''List the linting functions to be used and then
     exit''')
@arg('--only', nargs='+', help='''Only run this linting function. Can be used
     multiple times.''')
@arg('--exclude', nargs='+', help='''Exclude this linting function. Can be used
     multiple times.''')
@arg('--push-status', action='store_true', help='''If set, the lint status will
     be sent to the current commit on github. Also needs --user and --repo to
     be set. Requires the env var GITHUB_TOKEN to be set.''')
@arg('--commit', help='Commit on github on which to update status')
@arg('--user', help='Github user')
@arg('--repo', help='Github repo')
@arg('--git-range', help='Git range', nargs=2)
def lint(recipe_folder, config, packages="*", cache=None, list_funcs=False,
         only=None, exclude=None, push_status=False, user='bioconda',
         commit=None, repo='bioconda-recipes', git_range=None):
    """
    Lint recipes

    If --push-status is not set, reports a TSV of linting results to stdout.
    Otherwise pushes a commit status to the specified commit on github.
    """
    if list_funcs:
        print('\n'.join([i.__name__ for i in lint_functions.registry]))
        sys.exit(0)

    df = linting.channel_dataframe(cache=cache)
    registry = lint_functions.registry

    if only is not None:
        registry = list(filter(lambda x: x.__name__ in only, registry))
        if len(registry) == 0:
            sys.stderr.write('No valid linting functions selected, exiting.\n')
            sys.exit(1)

    # returns recipe_folder/package
    recipes = list(utils.get_recipes(recipe_folder, package=packages))

    if git_range:
        # returns recipe_folder/package/meta.yaml
        modified = utils.modified_recipes(git_range, recipe_folder, full=True)
        if not modified:
            logger.info('No recipe modified according to git, exiting.')
            return
        recipes = [os.path.dirname(f) for f in modified]
        logger.info('Recipes modified according to git: {}'.format(' '.join(packages)))

    report = linting.lint(
        recipes,
        config=config,
        df=df,
        registry=registry,
    )

    # the returned dataframe is in tidy format; summarize a bit to get a more
    # reasonable log
    summarized = pandas.DataFrame(
        dict(failed_tests=report.groupby('recipe')['check'].agg('unique')))
    if len(summarized) > 0:
        logger.error('The following recipes failed linting. See '
                     'https://bioconda.github.io for details:\n%s\n',
                     summarized)
        if push_status:
            github_integration.update_status(user, repo, commit, state='error',
                                             context='linting',
                                             description='linting failed, see travis log', target_url=None)
        sys.exit(1)
    else:
            update_status(user, repo, commit, state='success', context='linting',
                          description='linting passed', target_url=None)



@arg('recipe_folder', help='Path to top-level dir of recipes.')
@arg('config', help='Path to yaml file specifying the configuration')
@arg(
    '--packages',
    nargs="+",
    help='Glob for package[s] to build. Default is to build all packages. Can '
    'be specified more than once')
@arg('--git-range', nargs=2,
     help='Git range (e.g. commits or something like '
     '"master HEAD"). All recipes modified within this range will be built if '
     'not present in the channel.')
@arg('--testonly', help='Test packages instead of building')
@arg('--force',
     help='Force building the recipe even if it already exists in '
     'the bioconda channel')
@arg('--docker', action='store_true',
     help='Build packages in docker container.')
@arg('--loglevel', help="Set logging level (debug, info, warning, error, critical)")
@arg('--mulled-test', action='store_true', help="Run a mulled-build test on the built package")
@arg('--build_script_template', help='''Filename to optionally replace build
     script template used by the Docker container. By default use
     docker_utils.BUILD_SCRIPT_TEMPLATE. Only used if --docker is True.''')
@arg('--pkg_dir', help='''Specifies the directory to which container-built
     packages should be stored on the host. Default is to use the host's
     conda-bld dir. If --docker is not specified, then this argument is
     ignored.''')
@arg('--conda-build-version',
     help='''Version of conda-build to use if building
     in a docker container. Has no effect otherwise.''')
@arg('--quick', help='''To speed up filtering, do not consider any recipes that
     are > 2 days older than the latest commit to master branch.''')
@arg('--disable-travis-env-vars', action='store_true', help='''By default, any
     environment variables starting with TRAVIS are sent to the Docker
     container. Use this flag to disable that behavior.''')
def build(recipe_folder,
          config,
          packages="*",
          git_range=None,
          testonly=False,
          force=False,
          docker=None,
          loglevel="info",
          mulled_test=False,
          build_script_template=None,
          pkg_dir=None,
          conda_build_version=docker_utils.DEFAULT_CONDA_BUILD_VERSION,
          quick=False,
          disable_travis_env_vars=False,
          ):
    LEVEL = getattr(logging, loglevel.upper())
    logging.basicConfig(level=LEVEL, format='%(levelname)s:%(name)s:%(message)s')
    logging.getLogger('bioconda_utils').setLevel(getattr(logging, loglevel.upper()))
    cfg = utils.load_config(config)
    setup = cfg.get('setup', None)
    if setup:
        logger.debug("Running setup: %s" % setup)
        for cmd in setup:
            utils.run(shlex.split(cmd))
    if docker:
        if build_script_template is not None:
            build_script_template = open(build_script_template).read()
        else:
            build_script_template = docker_utils.BUILD_SCRIPT_TEMPLATE
        if pkg_dir is None:
            use_host_conda_bld = True
        else:
            use_host_conda_bld = False

        docker_builder = docker_utils.RecipeBuilder(
            build_script_template=build_script_template,
            pkg_dir=pkg_dir,
            use_host_conda_bld=use_host_conda_bld,
            conda_build_version=conda_build_version,
        )
    else:
        docker_builder = None

    # handle git range
    if git_range:
        modified = utils.modified_recipes(git_range)
        if not modified:
            logger.info('No recipe modified according to git, exiting.')
            exit(0)
        # obtain list of packages to build
        packages = [os.path.dirname(f) for f in modified]
        logger.info('Recipes modified according to git: {}'.format(' '.join(packages)))

    success = build_recipes(
        recipe_folder,
        config=config,
        packages=packages,
        testonly=testonly,
        force=force,
        mulled_test=mulled_test,
        docker_builder=docker_builder,
        quick=quick,
        disable_travis_env_vars=disable_travis_env_vars,
    )
    exit(0 if success else 1)


@arg('recipe_folder', help='Path to recipes directory')
@arg('--packages',
     nargs="+",
     help='Glob for package[s] to show in DAG. Default is to show all '
     'packages. Can be specified more than once')
@arg('--format', choices=['gml', 'dot'], help='Set format to print graph.')
@arg('--hide-singletons',
     action='store_true',
     help='Hide singletons in the printed graph.')
def dag(recipe_folder, packages="*", format='gml', hide_singletons=False):
    """
    Export the DAG of packages to a graph format file for visualization
    """
    dag = utils.get_dag(utils.get_recipes(recipe_folder, packages))[0]
    if hide_singletons:
        for node in nx.nodes(dag):
            if dag.degree(node) == 0:
                dag.remove_node(node)
    if format == 'gml':
        nx.write_gml(dag, sys.stdout.buffer)
    elif format == 'dot':
        write_dot(dag, sys.stdout)


@arg('recipe_folder', help='Path to recipes directory')
@arg('--dependencies', nargs='+',
     help='''Return recipes in `recipe_folder` in the dependency chain for the
     packages listed here. Answers the question "what does PACKAGE need?"''')
@arg('--reverse-dependencies', nargs='+',
     help='''Return recipes in `recipe_folder` in the reverse dependency chain
     for packages listed here. Answers the question "what depends on
     PACKAGE?"''')
@arg('--restrict',
     help='''Restrict --dependencies to packages in `recipe_folder`. Has no
     effect if --reverse-dependencies, which always looks just in the recipe
     dir.''')
@arg('--loglevel', help="Set logging level (debug, info, warning, error, critical)")
def dependent(recipe_folder, restrict=False, dependencies=None, reverse_dependencies=None, loglevel='warning'):
    """
    Print recipes dependent on a package
    """
    if dependencies and reverse_dependencies:
        raise ValueError(
            '`dependencies` and `reverse_dependencies` are mutually exclusive')

    LEVEL = getattr(logging, loglevel.upper())
    logging.basicConfig(level=LEVEL, format='%(levelname)s:%(name)s:%(message)s')
    logging.getLogger('bioconda_utils').setLevel(getattr(logging, loglevel.upper()))

    d, n2r = utils.get_dag(utils.get_recipes(recipe_folder, "*"), restrict=restrict)

    if reverse_dependencies is not None:
        func, packages = nx.algorithms.descendants, reverse_dependencies
    elif dependencies is not None:
        func, packages = nx.algorithms.ancestors, dependencies

    pkgs = []
    for pkg in packages:
        pkgs.extend(list(func(d, pkg)))
    print('\n'.join(sorted(pkgs)))


def main():
    argh.dispatch_commands([build, dag, dependent, lint])
