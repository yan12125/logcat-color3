from setuptools import setup

setup(
    # Can't be in setup.cfg
    # https://github.com/pypa/setuptools_scm/issues/181
    use_scm_version=True,
)
