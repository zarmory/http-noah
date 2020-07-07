#########
HTTP Noah
#########

.. image:: https://img.shields.io/pypi/v/http-noah.svg
    :target: https://pypi.python.org/pypi/http-noah

.. image:: https://img.shields.io/travis/haizaar/http-noah.svg
        :target: https://travis-ci.org/haizaar/http-noah

.. image:: https://img.shields.io/pypi/dm/http-noah.svg
    :target: https://pypi.python.org/pypi/http-noah


Generic HTTP client for sync (requests) and async (aiohttp) operations.

"Noah" means "convenient" in Hebrew.

For now I support Python 3.8+ only. Please open an issue if you need support for earlier options.

**********
Motivation
**********

If you have ever interfaced with REST APIs in Python it probably started like this

.. code-block:: python

  class PetSanctuaryClient:
      def __init__(self):
          self.session = requests.Session()

      def get(self, url):
          res = self.session.get(url)
          res.raise_for_status()
          return res.json()

From this point it obviously gets complicated really quickly... ``.jsoin()`` returns you dict or list, but usually
you want to at least validate it somehow or even better use a specialty tool like `Pydantic <https://pydantic-docs.helpmanual.io/>`_.
Continuing the above hypothetical example

.. code-block:: python

  from pydantic import BaseModel, ValidationError
  from typing import List

  class Pet(BaseModel):
      name: str

  class Pets(BaseModel):
      __root__ = List[Pet]

  class PetSanctuaryClient:
      ...

      def list_pets(self) -> Pets:
          pets_info = self.get(...)
          try:
              return Pets.parse_obj(pets_info)
          except ValidationError:
              logger.info("Failed to parse pets_info", pets_info=pets_info)  # hooray structlog

The above has to be properly factored out of course and you end up with the following class signature:

.. code-block:: python

  class PetSanctuaryClient:
      def list_pets(...)
      def get_pet(...)
      def delete_pet(...)
      def assign_pet_to_carer(...)
      def list_carers(...)
      def get_carer(...)
      ...

If your target API is anything above trivial you'll quickly end up with entangled mess of methods.
Naming conventions help of course but it quickly becomes a monster of a class.
If we could only break down this monolithic contraption into sub-APIs implemented in their separate classes
which we would then hierarchically plug into the main?  I believe the below is much easier to digest:

.. code-block:: python

  psc = PetSanctuaryClient(...)
  psc.pets.get(..)
  psc.pets.list(...)
  psc.cares.list(...)
  ...

I hope this gives you an idea of why this project was born. Throw into the equation support for asyncio and
numerous corner cases like forming URLs, aiohttp releasing connection on ``.raise_for_status()`` invocation and hence
denying you from seeing the error body which quite often contains  valuable information, etc.

All this particularly started to make sense when I switched to using
`FastAPI <https://fastapi.tiangolo.com/>`_ for my backend services and already had Pydantic
models that I could reuse on the client side.


************
Installation
************
There are ``sync`` and ``async`` flavours to installation to make sure only
relevant dependencies are pulled (e.g. chances are you don't want aiohttp in your sync app).

Sync version::

  pip install --upgrade http-noah[sync]

Async version::

  pip install --upgrade http-noah[async]

To install both sync and async versions use ``all`` extra specification instead of ``sync`` / ``async``.

*****
Usage
*****

Basic example
#############
Let's start with a basic example.
Assuming our Pet Sanctuary API is running on ``http://localhost:8080/api/v1``:

.. code-block:: python

  from pydantic import BaseModel
  from http_noah.sync_client import SyncHTTPClient

  class Pet(BaseModel):
      name: str

  def main():
      with SyncHTTPClient("localhost", 8080) as client:
          pet: Pet = client.get("/pets/1", response_type=Pet)

Let's have a closer looks at what happened here:

* We provided only ``host`` and ``port`` with ``api_base`` defaulting to ``/api/v1`` so that
  we don't have to prepend it to every URL in our call
* We ask http_noah to convert API response to an instance of the desired type (or raise
  otherwise)
* We used a context manager to make sure everything will be cleaned up promptly.
  In a more complex code, you may consider a kind of a life-cycle manager e.g. like in my demo
  Hanuka project (`source <https://github.com/haizaar/hanuka/blob/master/hanuka/main.py#L36>`_)

Async example is pretty much the same:

.. code-block:: python

  from http_noah.async_client import AsyncHTTPClient

  async def main():
      async with AsyncHTTPClient("localhost", 8080) as client:
          pet: Pet = await client.get("/pets/1", response_type=Pet)

Since the goal of this library is to provide similar interfaces for both sync and async
code I'll focus on *async* examples from now on and will be leaving notes if there are
differences that I worked hard to reduce to a very few.

The client support the following methods that map the corresponding HTTP verbs:

.. code-block:: python

  .get(...)
  .post(...)
  .put(...)
  .delete(...)

Sending your data back is easy as well - be it just a dict or Pydantic model.

For Pydantic models you can just pass them to the ``body`` argument of e.g. ``.post()``:

.. code-block:: python

  async def create_pet():
      async with AsyncHTTPClient("localhost", 8080) as client:
          pet = Pet(name="Crispy")
          await client.post("/pets", body=pet, response_type=Pet)

If you just want to send data as JSON you need to outline that explicitly:

.. code-block:: python

  from http_noah.common import JSONData

  async def create_pet():
      async with AsyncHTTPClient("localhost", 8080) as client:
          pet = {"name": "Crispy"}
          await client.post("/pets", body=JSONData(data=pet), response_type=Pet)

This is necessary for http_noah to understand whether your intent is to send you data
as JSON or as Form which both can be Python dicts. See more on forms and file uploads
in the dedicated section below.

Again, I prefer to model everything I send and receive with Pydantic models - it makes
life so much easier that you get addicted to it very fast.

Nested Clients
##############
Now when we understand the basic usage let's see how can we build those beautiful nested
clients I promised you in the beginning.

Let's build a client for our hypothetical pet sanctuary API by starting with the root class:

.. code-block:: python

  from http_noah.async_client import AsyncAPIClientBase, AsyncHTTPClient

  class PetSanctuaryClient(AsyncAPIClientBase):
      @classmethod
      def new(cls, host: str, port: int, scheme: str = "https") -> PetSanctuaryClient:
          client = AsyncHTTPClient(host=host, port=port, scheme=scheme)
          return cls(client=client)

A this point it's just a boilerplate class that does nothing spectacular except having
a builder function. Note that I use ``AsyncAPIClientBase`` and not ``AsyncHTTPClient``.

Now let's implement Pets sub-API:

.. code-block:: python

  from dataclasses import dataclass
  from http_noah.async_client import AsyncAPIClientBase, AsyncHTTPClient

  # Skipped model definitions here - as in the basic example

  @dataclass
  class PetClient:
      client: AsyncHTTPClient

      class paths:
          prefix: str = "/pets"
          list: str = prefix
          get: str = prefix + "/{id}"
          create: str = prefix

      async def list(self) -> Pets:
          return await self.client.get(self.paths.list, response_type=Pets)

      async def get(self, id: int) -> Pet:
          return await self.client.get(self.paths.get.format(id=id), response_type=Pet)

      async def create(self, pet: Pet) -> Pet:
          return await self.client.post(self.paths.create, body=Pet, response_type=Pet)

  @dataclass
  class PetSanctuaryClient(AsyncAPIClientBase):
      pets: PetClient

      @classmethod
      def new(cls, host: str, port: int, scheme: str = "https") -> PetSanctuaryClient:
          client = AsyncHTTPClient(host=host, port=port, scheme=scheme)
          pet_client = PetClient(client)
          return cls(client=client, pets=pet_client)

Now we are talking! Let's enjoy it:

.. code-block:: python

    psc = PetSanctuaryClient("localhost", 8080, scheme="http")
    async with psc:
        pets = await psc.pets.list()
        pet = await psc.pets.get(1)

Similarly we can implement other sub-API clients and nest them easily.


Getting serious
###############

Response type
=============
Specifying response type is **mandatory** *unless* you expect your request to respond with
HTTP 204 "No Content" which generally makes sense for DELETE operations.

* If response Content-Type heading is set to ``applicaiton/json`` then JSON data will be
  decoded for you and can be further parsed using `Pydantic <https://pydantic-docs.helpmanual.io/>`_
  model of your choice.
* Otherwise, you can request back either ``str`` or ``bytes``

This results in a limitation where with this library you can't fetch JSON response back
as string. But since this is a high-level REST client I've yet bumped into this limitation
in practice.

To sum it up, here are your options for the ``response_type`` argument:

* ``bytes`` when a request returns a binary data, e.g image
* ``str`` when a request returns text (technically speaking "when the content type is not ``application/json``")
* ``dict``, ``list``, ``int``, ``bool``, ``float``, ``str`` (i.e. any of the JSON -> Python native types),
  when your request returns JSON data and you don't want it parsed further into Pydantic objects.

Error handling
==============
Trying to align between sync and async code I aliased common error base classes under
common names ``ConnectionError``, ``HTTPError``, and ``TimeoutError`` in both
``http_noah.sync_client`` and ``async_client``. This is where it stops though - behind the
name these are still ``requests`` / ``aiohttp`` error classes if you want to dig deeper.

One useful thing that http_noah does for you is making sure to log HTTP body when the error occurs.
This is usually a small but vital piece of information to help you understand what's going
on. Sadly enough, it requires quite a bit of tinkering to dig this info out.
Just one example is that calling aiohttp's response object ``raise_for_status()`` method
will actually return the underlying HTTP connection back to the pool depriving you of reading
the error body.

Again, http_noah will log HTTP (error) body when it encounters HTTP errors.

Timeouts
========
Timeouts can be configured by passing instance of ``http_noah.common.Timeout`` class to
either ``.get()``, ``put()``, etc. methods or setting it per client instance through
``ClientOptions``:

.. code-block:: python

  from http_noah.common import ClientOptions, Timeout
  from http_noah.async_client import AsyncHTTPClient

  options = ClientOptions(Timeout(total=10)
  async with AsyncHTTPClient(host="localhost", port=80, options=options) as client:
      await client.get(...)  # Limited to 10 seconds
      await client.post(..., timeout=Timeout(total=20))  # per call override

However, if you reflect on the nested client approach as was suggested earlier, you can quickly notice
that re-defining ``timeout`` argument in all your high-level methods is very onerous.
Fortunately, http_noah stands true to its name and provides an easy solution with
the help of ``timeout`` context manager that both sync and async client implements:

Continuing our ``PetSanctuaryClient`` example:

.. code-block:: python

  from http_noah.common import Timeout

  async with PetSanctuaryClient("localhost", 8080, scheme="http") as psc:
      pets = await psc.pets.list()
      with psc.client.timeout(Timeout(total=1):
          pet = await psc.pets.get(1)  # Limited to 1 second

As you can see, neither ``PetClient`` nor ``PetSanctuaryClient`` defined any timeout
logic yet we can perfectly apply timeouts.

.. note::
  One difference between sync and async behaviour here is that in case of connection
  timeout, aiohttp will raise ``async.TimeoutError`` where requests will raise
  ``requests.exceptions.ConnectionError`` which is technically not a TimeoutError.

  See ``test_connect_timeout`` tests under ``tests/async_tests.py`` and
  ``tests/sync_tests.py`` for details.

Forms
=====
Forms are not used much today. However, I still encounter them when I need to login
into API to get Bearer token.

To use a form with http_noah simply fill it up as a ``dict``, as you would with
aiohttp / requests, and pass it through ``body`` argument wrapped with ``FormData``:

.. code-block:: python

  from typing import Literal
  from pydantic import BaseModel
  from http_noah.common import FormData

  class TokenResponse(BaseModel):
      access_token: str
      token_type: Literal["bearer"]

  async def get_access_token():
      login_form = FormData(data={
          "grant_type": "password",
          "username": "foo",
          "password": "secret",
      })
      async with AsyncHTTPClient("localhost", 8080) as client:
          tr = await client.post("/access_token", body=login_form, response_type=TokenResponse)

Files
=====
http-noah provides simple means to upload a file as a multipart encoded form.
Best illustrated by example:

.. code-block:: python

  from pathlib import Path

  from http_noah.common import UploadFile

  async with AsyncHTTPClient("localhost", 8080) as client:
      await client.post(
          "/pets/1/photo",
          body=UploadFile(name="thumbnail", path=Path("myphoto.jpg"),
      )

SSL
===
SSL/TLS are supported as they are in ``requests`` and ``aiohttp``. Sometimes however
it's desirable to disable SSL validation, e.g. in your dev environment. This can be
done through ``ClientOptions``:

.. code-block:: python

  from http_noah.common import ClientOptions
  from http_noah.async_client import AsyncHTTPClient

  options = ClientOptions(ssl_verify_cert=False)
  async with AsyncHTTPClient(host="localhost", port=80, options=options) as client:
      ...


***********
Development
***********
To develop http_noah you'll need Python 3.8+, pipenv and `direnv <https://direnv.net/>`_ installed.

Then just run ``make bootstrap`` after cloning the repo, wait a while, and you are done - next time you enter into the
cloned directory the environment will be set for you.

Code wise, you can't really have the same code that does both sync and async. Not in a readable way at least.
Since readability counts and simplicity trumps complexity, I'd rather have two versions of a very simple code
that does each of sync and async instead of one callback-polluted/iterator-based/black-magic-imbued code-base.

Care was takes to have a functional tests for each of the library features.

Enjoy and see you at PRs!
