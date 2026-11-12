from __future__ import annotations

import inspect

import browserless_bap as bap
import browserless_bap.sync_api as sync_bap


def test_every_public_async_method_has_identical_sync_twin() -> None:
    for class_name in ("Page", "Browser", "Browserless", "ElementHandle"):
        async_class = getattr(bap, class_name)
        sync_class = getattr(sync_bap, class_name)
        for method_name, async_method in inspect.getmembers(async_class):
            if method_name.startswith("_") or not inspect.iscoroutinefunction(
                async_method
            ):
                continue
            sync_method = getattr(sync_class, method_name, None)
            assert sync_method is not None, f"{class_name}.{method_name} missing"
            assert not inspect.iscoroutinefunction(sync_method)
            assert inspect.signature(sync_method) == inspect.signature(async_method), (
                f"{class_name}.{method_name} signature drift"
            )
