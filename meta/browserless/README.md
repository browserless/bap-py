# browserless

This package installs [browserless-bap](https://pypi.org/project/browserless-bap/),
the Python client for Browserless's Browser Automation Protocol. It contains no
code of its own, so these two commands install the same SDK:

```bash
pip install browserless
pip install browserless-bap
```

Import the SDK as `browserless_bap`:

```python
import browserless_bap as bap
```

See the [browserless-bap README](https://github.com/browserless/bap-py#readme)
and the [API reference](https://docs.browserless.io/bap/python/reference).
