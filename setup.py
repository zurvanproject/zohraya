"""Exclude repository-only tests; no control state or credentials are packaged."""
from setuptools import setup
from setuptools.command.build_py import build_py


class RuntimeOnlyBuild(build_py):
    def find_package_modules(self, package, package_dir):
        return [row for row in super().find_package_modules(package, package_dir)
                if not row[1].startswith('test_')]


setup(cmdclass={'build_py': RuntimeOnlyBuild})
