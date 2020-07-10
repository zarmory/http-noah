#!/usr/bin/env python

from setuptools import find_packages, setup

LICENSE = "LICENSE"
README = "README.txt"

with open("README.rst") as f:
    readme = f.read()

with open("LICENSE") as f:
    license = f.read()


setup(
    name="http-noah",
    version="0.1.6",
    description="REST-minded yet generic HTTP Python client with both async and sync interfaces",
    long_description=readme,
    author="Zaar Hai",
    author_email="haizaar@haizaar.com",
    url="https://github.com/haizaar/http-noah",
    license=license,
    packages=find_packages(),
    install_requires=[
        "structlog",
        "pydantic",
    ],
    extras_require={
        "async": ["aiohttp"],
        "sync": ["requests"],
        "all": ["aiohttp", "requests"],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.8",
    ],
    data_files=[("", [LICENSE, README])],
)
