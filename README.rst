#########
HTTP Noah
#########

"Noah" mean convenient in Hebrew.
Generic HTTP client for for sync (requests) and async (aiohttp) operations.


****
TODO
****

* Log connection attempts and details


************
Installation
************
There are ``sync`` and ``async`` flavours to installation to make sure only
relevant dependencies are pulled (e.g. you don't want aiohttp in your sync app).

Sync version::

  pip install --upgrade http-noah[sync]

Async version::

  pip install --upgrade http-noah[async]

To install both sync and async versions use ``all`` extra specification instead of ``sync`` / ``async``.


***********
Development
***********
`Direnv <https://direnv.net/`_  makes like easier. Get it installed and then run ``make boostrap``
(well, I do asume that you have ``make`` and Python installed).
