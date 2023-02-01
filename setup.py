from setuptools import setup

setup(
    name="BlackDwarf",
    version="0.0.2",
    author="LordOfPolls",
    author_email="dev@lordofpolls.com",
    description="A script to eliminate wildcard imports from Python code",
    license="MIT",
    keywords="python wildcard imports",
    entry_points={"console_scripts": ["blackdwarf = main:entry_point"]},
    requires=["black"],
)
