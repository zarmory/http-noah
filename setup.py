from setuptools import find_packages, setup

setup(
    name="http-noah",
    version="0.0.0",
    url="https://github.com/haizaar/http-noah",
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
)
